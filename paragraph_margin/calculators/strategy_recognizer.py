"""Strategy recognizer — identifies multi-leg option strategies from positions.

Uses a greedy algorithm that tries to match more complex/specific strategies
first, then falls back to simpler patterns. Unmatched positions are returned
separately for individual margin calculation.

Recognition priority:
0. Cross-asset (convertible bond + equity arbitrage)
1. Cross-product with stock (conversion, collar, covered call, protective put)
2. 4-leg pure option (box spread, iron condor/butterfly, butterflies, short butterflies, condors)
3. Ratio spreads / backspreads (unequal leg quantities)
4. Synthetics (call + put, opposite sides, same strike/expiry)
5. 2-leg same expiry (straddles, strangles, verticals)
6. 2-leg different expiry (calendar, diagonal)
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from paragraph_margin.models.enums import OptionType, PositionSide, SecurityType, StrategyType
from paragraph_margin.models.positions import Position
from paragraph_margin.models.securities import CorporateBond, Equity, Option
from paragraph_margin.models.strategies import RecognizedStrategy, StrategyGroup, StrategyLeg
from paragraph_margin.money import ZERO


@dataclass
class _PoolEntry:
    """Tracks an option position's remaining unmatched quantity."""

    position: Position
    option: Option
    remaining: Decimal

    @property
    def side(self) -> PositionSide:
        return self.position.side

    @property
    def strike(self) -> Decimal:
        return self.option.strike

    @property
    def expiry(self) -> date:
        return self.option.expiration

    @property
    def option_type(self) -> OptionType:
        return self.option.option_type

    @property
    def is_call(self) -> bool:
        return self.option_type == OptionType.CALL

    @property
    def is_put(self) -> bool:
        return self.option_type == OptionType.PUT

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        return self.side == PositionSide.SHORT

    def consume(self, qty: Decimal) -> None:
        self.remaining -= qty

    @property
    def exhausted(self) -> bool:
        return self.remaining <= ZERO


@dataclass
class _EquityPoolEntry:
    """Tracks an equity position's remaining unmatched quantity (in shares)."""

    position: Position
    remaining: Decimal  # shares

    @property
    def side(self) -> PositionSide:
        return self.position.side

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        return self.side == PositionSide.SHORT

    def consume(self, shares: Decimal) -> None:
        self.remaining -= shares

    @property
    def exhausted(self) -> bool:
        return self.remaining <= ZERO


@dataclass
class _BondPoolEntry:
    """Tracks a convertible bond position's remaining unmatched quantity."""

    position: Position
    bond: CorporateBond
    remaining: Decimal

    @property
    def side(self) -> PositionSide:
        return self.position.side

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        return self.side == PositionSide.SHORT

    @property
    def conversion_ratio(self) -> Decimal:
        return self.bond.conversion_ratio or Decimal("1")

    def consume(self, qty: Decimal) -> None:
        self.remaining -= qty

    @property
    def exhausted(self) -> bool:
        return self.remaining <= ZERO


def _next_id(prefix: str) -> str:
    uid = uuid.uuid4().hex[:8]
    return f"{prefix}_{uid}"


class StrategyRecognizer:
    """Identifies multi-leg option strategies from a set of positions."""

    def recognize(
        self,
        positions: list[Position],
        underlying_prices: dict[str, Decimal] | None = None,
    ) -> StrategyGroup:
        """Recognize strategies from a set of positions."""
        account_id = positions[0].account_id if positions else ""
        groups = self._group_by_underlying(positions)

        all_strategies: list[RecognizedStrategy] = []
        all_unmatched: list[Position] = []

        for symbol, group_pos in groups.items():
            strategies, unmatched = self._recognize_group(symbol, group_pos)
            all_strategies.extend(strategies)
            all_unmatched.extend(unmatched)

        return StrategyGroup(
            account_id=account_id,
            strategies=all_strategies,
            unmatched_positions=all_unmatched,
        )

    # --- Grouping ---

    def _group_by_underlying(
        self, positions: list[Position]
    ) -> dict[str, list[Position]]:
        groups: dict[str, list[Position]] = defaultdict(list)
        for pos in positions:
            sec = pos.security
            if isinstance(sec, Option):
                groups[sec.underlying_symbol].append(pos)
            elif isinstance(sec, Equity):
                groups[sec.symbol].append(pos)
            elif isinstance(sec, CorporateBond) and sec.convertible and sec.conversion_underlying:
                # Route convertible bonds to the underlying equity's group
                groups[sec.conversion_underlying].append(pos)
            else:
                groups["_other_"].append(pos)
        return dict(groups)

    def _recognize_group(
        self,
        symbol: str,
        positions: list[Position],
    ) -> tuple[list[RecognizedStrategy], list[Position]]:
        if symbol == "_other_":
            return [], positions

        equity_pool = [
            _EquityPoolEntry(p, abs(p.quantity))
            for p in positions
            if isinstance(p.security, Equity)
        ]
        option_pool = [
            _PoolEntry(p, p.security, abs(p.quantity))
            for p in positions
            if isinstance(p.security, Option)
        ]
        bond_pool = [
            _BondPoolEntry(p, p.security, abs(p.quantity))
            for p in positions
            if isinstance(p.security, CorporateBond) and p.security.convertible
        ]

        strategies: list[RecognizedStrategy] = []

        # Priority 0: Cross-asset (convertible bond + equity)
        if bond_pool:
            self._try_convertible_arb(symbol, bond_pool, equity_pool, strategies)

        # Priority 1: Cross-product (stock + options)
        self._recognize_cross_product(symbol, equity_pool, option_pool, strategies)

        # Priority 2: 4-leg pure option
        self._recognize_four_leg(symbol, option_pool, strategies)

        # Priority 3: Ratio spreads (before verticals — unequal quantities)
        self._recognize_ratio_spreads(symbol, option_pool, strategies)

        # Priority 4: Synthetics (call + put, opposite sides, same strike/expiry)
        self._try_synthetics(symbol, option_pool, strategies)

        # Priority 5: 2-leg same expiry (verticals, straddles, strangles)
        self._recognize_two_leg_same_expiry(symbol, option_pool, strategies)

        # Priority 6: 2-leg different expiry (calendar, diagonal)
        self._recognize_two_leg_diff_expiry(symbol, option_pool, strategies)

        # Collect unmatched
        unmatched: list[Position] = []
        for e in equity_pool:
            if not e.exhausted:
                unmatched.append(
                    e.position.model_copy(update={"quantity": e.remaining})
                )
        for o in option_pool:
            if not o.exhausted:
                unmatched.append(
                    o.position.model_copy(update={"quantity": o.remaining})
                )
        for b in bond_pool:
            if not b.exhausted:
                unmatched.append(
                    b.position.model_copy(update={"quantity": b.remaining})
                )

        return strategies, unmatched

    # ================================================================
    # Cross-asset strategies (convertible bond + equity)
    # ================================================================

    def _try_convertible_arb(
        self,
        symbol: str,
        bond_pool: list[_BondPoolEntry],
        equity_pool: list[_EquityPoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Convertible arbitrage: long convertible bond + short underlying equity.

        Matches by conversion_underlying. The bond's conversion_ratio determines
        how many shares each bond converts to. We match the lesser of the bond's
        equivalent share count and the short equity quantity.
        """
        for bp in bond_pool:
            if bp.exhausted or not bp.is_long:
                continue
            for eq in equity_pool:
                if eq.exhausted or not eq.is_short:
                    continue
                # Compute how many shares the remaining bonds convert to
                bond_equivalent_shares = bp.remaining * bp.conversion_ratio
                matchable_shares = min(bond_equivalent_shares, eq.remaining)
                if matchable_shares <= ZERO:
                    continue
                # How many bonds are consumed (may be fractional — floor to whole bonds)
                bonds_consumed = min(bp.remaining, matchable_shares / bp.conversion_ratio)
                if bonds_consumed <= ZERO:
                    continue
                shares_consumed = bonds_consumed * bp.conversion_ratio

                bp.consume(bonds_consumed)
                eq.consume(shares_consumed)
                strategies.append(RecognizedStrategy(
                    strategy_id=_next_id("cvt_arb"),
                    strategy_type=StrategyType.CONVERTIBLE_ARB,
                    legs=[
                        StrategyLeg(
                            position=bp.position.model_copy(update={"quantity": bonds_consumed}),
                            role="long_convertible",
                            ratio=int(bonds_consumed),
                        ),
                        StrategyLeg(
                            position=eq.position.model_copy(update={"quantity": shares_consumed}),
                            role="short_equity_hedge",
                            ratio=int(shares_consumed),
                        ),
                    ],
                    underlying_symbol=symbol,
                    description=(
                        f"Convertible arb: {int(bonds_consumed)} bonds "
                        f"({bp.conversion_ratio}:1) + {int(shares_consumed)} short {symbol}"
                    ),
                ))

    # ================================================================
    # Cross-product strategies (stock + options)
    # ================================================================

    def _recognize_cross_product(
        self,
        symbol: str,
        equity_pool: list[_EquityPoolEntry],
        option_pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        # Try conversions/reversals first (most specific: same strike put + call + stock)
        self._try_conversions_reversals(symbol, equity_pool, option_pool, strategies)
        # Then collars (stock + put + call, different strikes)
        self._try_collars(symbol, equity_pool, option_pool, strategies)
        # Then covered calls and protective puts
        self._try_covered_calls(symbol, equity_pool, option_pool, strategies)
        self._try_covered_puts(symbol, equity_pool, option_pool, strategies)
        self._try_protective_puts(symbol, equity_pool, option_pool, strategies)
        self._try_protective_calls(symbol, equity_pool, option_pool, strategies)

    def _try_conversions_reversals(
        self,
        symbol: str,
        equity_pool: list[_EquityPoolEntry],
        option_pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Conversion: long stock + long put + short call (same strike, same expiry).
        Reverse conversion: short stock + short put + long call (same strike, same expiry)."""
        for eq in equity_pool:
            if eq.exhausted:
                continue

            if eq.is_long:
                # Conversion: long stock + long put + short call, same strike, same expiry
                long_puts = [
                    o for o in option_pool
                    if not o.exhausted and o.is_long and o.is_put
                ]
                short_calls = [
                    o for o in option_pool
                    if not o.exhausted and o.is_short and o.is_call
                ]
                for lp in long_puts:
                    if eq.exhausted:
                        break
                    for sc in short_calls:
                        if eq.exhausted or lp.exhausted:
                            break
                        # Same strike AND same expiry required
                        if lp.strike != sc.strike or lp.expiry != sc.expiry:
                            continue
                        multiplier = lp.option.contract_multiplier
                        matchable = min(
                            eq.remaining // multiplier,
                            lp.remaining,
                            sc.remaining,
                        )
                        if matchable <= ZERO:
                            continue
                        shares_used = matchable * multiplier
                        eq.consume(shares_used)
                        lp.consume(matchable)
                        sc.consume(matchable)
                        strategies.append(RecognizedStrategy(
                            strategy_id=_next_id("conversion"),
                            strategy_type=StrategyType.CONVERSION,
                            legs=[
                                StrategyLeg(
                                    position=eq.position.model_copy(update={"quantity": shares_used}),
                                    role="underlying_long",
                                    ratio=int(shares_used),
                                ),
                                StrategyLeg(
                                    position=lp.position.model_copy(update={"quantity": matchable}),
                                    role="long_put",
                                    ratio=int(matchable),
                                ),
                                StrategyLeg(
                                    position=sc.position.model_copy(update={"quantity": matchable}),
                                    role="short_call",
                                    ratio=int(matchable),
                                ),
                            ],
                            underlying_symbol=symbol,
                            description=f"Conversion: {int(shares_used)} shares + {int(matchable)} {lp.strike} put/call",
                        ))

            elif eq.is_short:
                # Reverse conversion: short stock + short put + long call, same strike, same expiry
                short_puts = [
                    o for o in option_pool
                    if not o.exhausted and o.is_short and o.is_put
                ]
                long_calls = [
                    o for o in option_pool
                    if not o.exhausted and o.is_long and o.is_call
                ]
                for sp in short_puts:
                    if eq.exhausted:
                        break
                    for lc in long_calls:
                        if eq.exhausted or sp.exhausted:
                            break
                        # Same strike AND same expiry required
                        if sp.strike != lc.strike or sp.expiry != lc.expiry:
                            continue
                        multiplier = sp.option.contract_multiplier
                        matchable = min(
                            eq.remaining // multiplier,
                            sp.remaining,
                            lc.remaining,
                        )
                        if matchable <= ZERO:
                            continue
                        shares_used = matchable * multiplier
                        eq.consume(shares_used)
                        sp.consume(matchable)
                        lc.consume(matchable)
                        strategies.append(RecognizedStrategy(
                            strategy_id=_next_id("reverse_conversion"),
                            strategy_type=StrategyType.REVERSE_CONVERSION,
                            legs=[
                                StrategyLeg(
                                    position=eq.position.model_copy(update={"quantity": shares_used}),
                                    role="underlying_short",
                                    ratio=int(shares_used),
                                ),
                                StrategyLeg(
                                    position=sp.position.model_copy(update={"quantity": matchable}),
                                    role="short_put",
                                    ratio=int(matchable),
                                ),
                                StrategyLeg(
                                    position=lc.position.model_copy(update={"quantity": matchable}),
                                    role="long_call",
                                    ratio=int(matchable),
                                ),
                            ],
                            underlying_symbol=symbol,
                            description=f"Reverse conversion: {int(shares_used)} short shares + {int(matchable)} {sp.strike} put/call",
                        ))

    def _try_covered_calls(
        self,
        symbol: str,
        equity_pool: list[_EquityPoolEntry],
        option_pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Covered call: long stock + short call."""
        for eq in equity_pool:
            if eq.exhausted or not eq.is_long:
                continue
            short_calls = [
                o for o in option_pool
                if not o.exhausted and o.is_short and o.is_call
            ]
            for sc in short_calls:
                if eq.exhausted:
                    break
                multiplier = sc.option.contract_multiplier
                # How many contracts can the shares cover?
                coverable = min(
                    eq.remaining // multiplier,
                    sc.remaining,
                )
                if coverable <= ZERO:
                    continue
                shares_used = coverable * multiplier
                eq.consume(shares_used)
                sc.consume(coverable)
                strategies.append(RecognizedStrategy(
                    strategy_id=_next_id("covered_call"),
                    strategy_type=StrategyType.COVERED_CALL,
                    legs=[
                        StrategyLeg(
                            position=eq.position.model_copy(update={"quantity": shares_used}),
                            role="underlying_long",
                            ratio=int(shares_used),
                        ),
                        StrategyLeg(
                            position=sc.position.model_copy(update={"quantity": coverable}),
                            role="short_call",
                            ratio=int(coverable),
                        ),
                    ],
                    underlying_symbol=symbol,
                    description=f"Covered call: {int(shares_used)} shares + {int(coverable)} short {sc.strike} calls",
                ))

    def _try_covered_puts(
        self,
        symbol: str,
        equity_pool: list[_EquityPoolEntry],
        option_pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Covered put: short stock + short put."""
        for eq in equity_pool:
            if eq.exhausted or not eq.is_short:
                continue
            short_puts = [
                o for o in option_pool
                if not o.exhausted and o.is_short and o.is_put
            ]
            for sp in short_puts:
                if eq.exhausted:
                    break
                multiplier = sp.option.contract_multiplier
                coverable = min(eq.remaining // multiplier, sp.remaining)
                if coverable <= ZERO:
                    continue
                shares_used = coverable * multiplier
                eq.consume(shares_used)
                sp.consume(coverable)
                strategies.append(RecognizedStrategy(
                    strategy_id=_next_id("covered_put"),
                    strategy_type=StrategyType.COVERED_PUT,
                    legs=[
                        StrategyLeg(
                            position=eq.position.model_copy(update={"quantity": shares_used}),
                            role="underlying_short",
                            ratio=int(shares_used),
                        ),
                        StrategyLeg(
                            position=sp.position.model_copy(update={"quantity": coverable}),
                            role="short_put",
                            ratio=int(coverable),
                        ),
                    ],
                    underlying_symbol=symbol,
                    description=f"Covered put: {int(shares_used)} short shares + {int(coverable)} short {sp.strike} puts",
                ))

    def _try_protective_puts(
        self,
        symbol: str,
        equity_pool: list[_EquityPoolEntry],
        option_pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Protective put: long stock + long put."""
        for eq in equity_pool:
            if eq.exhausted or not eq.is_long:
                continue
            long_puts = [
                o for o in option_pool
                if not o.exhausted and o.is_long and o.is_put
            ]
            for lp in long_puts:
                if eq.exhausted:
                    break
                multiplier = lp.option.contract_multiplier
                matchable = min(eq.remaining // multiplier, lp.remaining)
                if matchable <= ZERO:
                    continue
                shares_used = matchable * multiplier
                eq.consume(shares_used)
                lp.consume(matchable)
                strategies.append(RecognizedStrategy(
                    strategy_id=_next_id("protective_put"),
                    strategy_type=StrategyType.PROTECTIVE_PUT,
                    legs=[
                        StrategyLeg(
                            position=eq.position.model_copy(update={"quantity": shares_used}),
                            role="underlying_long",
                            ratio=int(shares_used),
                        ),
                        StrategyLeg(
                            position=lp.position.model_copy(update={"quantity": matchable}),
                            role="long_put",
                            ratio=int(matchable),
                        ),
                    ],
                    underlying_symbol=symbol,
                    description=f"Protective put: {int(shares_used)} shares + {int(matchable)} long {lp.strike} puts",
                ))

    def _try_protective_calls(
        self,
        symbol: str,
        equity_pool: list[_EquityPoolEntry],
        option_pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Protective call: short stock + long call."""
        for eq in equity_pool:
            if eq.exhausted or not eq.is_short:
                continue
            long_calls = [
                o for o in option_pool
                if not o.exhausted and o.is_long and o.is_call
            ]
            for lc in long_calls:
                if eq.exhausted:
                    break
                multiplier = lc.option.contract_multiplier
                matchable = min(eq.remaining // multiplier, lc.remaining)
                if matchable <= ZERO:
                    continue
                shares_used = matchable * multiplier
                eq.consume(shares_used)
                lc.consume(matchable)
                strategies.append(RecognizedStrategy(
                    strategy_id=_next_id("protective_call"),
                    strategy_type=StrategyType.PROTECTIVE_CALL,
                    legs=[
                        StrategyLeg(
                            position=eq.position.model_copy(update={"quantity": shares_used}),
                            role="underlying_short",
                            ratio=int(shares_used),
                        ),
                        StrategyLeg(
                            position=lc.position.model_copy(update={"quantity": matchable}),
                            role="long_call",
                            ratio=int(matchable),
                        ),
                    ],
                    underlying_symbol=symbol,
                    description=f"Protective call: {int(shares_used)} short shares + {int(matchable)} long {lc.strike} calls",
                ))

    def _try_collars(
        self,
        symbol: str,
        equity_pool: list[_EquityPoolEntry],
        option_pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Collar: long stock + long put + short call (same expiry)."""
        for eq in equity_pool:
            if eq.exhausted or not eq.is_long:
                continue
            long_puts = [
                o for o in option_pool
                if not o.exhausted and o.is_long and o.is_put
            ]
            short_calls = [
                o for o in option_pool
                if not o.exhausted and o.is_short and o.is_call
            ]
            for lp in long_puts:
                if eq.exhausted:
                    break
                for sc in short_calls:
                    if eq.exhausted or lp.exhausted:
                        break
                    # Same expiry required
                    if lp.expiry != sc.expiry:
                        continue
                    # Put strike should be below call strike
                    if lp.strike >= sc.strike:
                        continue
                    multiplier = lp.option.contract_multiplier
                    matchable = min(
                        eq.remaining // multiplier,
                        lp.remaining,
                        sc.remaining,
                    )
                    if matchable <= ZERO:
                        continue
                    shares_used = matchable * multiplier
                    eq.consume(shares_used)
                    lp.consume(matchable)
                    sc.consume(matchable)
                    strategies.append(RecognizedStrategy(
                        strategy_id=_next_id("collar"),
                        strategy_type=StrategyType.COLLAR,
                        legs=[
                            StrategyLeg(
                                position=eq.position.model_copy(update={"quantity": shares_used}),
                                role="underlying_long",
                                ratio=int(shares_used),
                            ),
                            StrategyLeg(
                                position=lp.position.model_copy(update={"quantity": matchable}),
                                role="long_put",
                                ratio=int(matchable),
                            ),
                            StrategyLeg(
                                position=sc.position.model_copy(update={"quantity": matchable}),
                                role="short_call",
                                ratio=int(matchable),
                            ),
                        ],
                        underlying_symbol=symbol,
                        description=f"Collar: {int(shares_used)} shares + {int(matchable)} {lp.strike}/{sc.strike} put/call",
                    ))

    # ================================================================
    # 4-leg pure option strategies
    # ================================================================

    def _recognize_four_leg(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        self._try_box_spreads(symbol, pool, strategies)
        self._try_iron_condors(symbol, pool, strategies)
        self._try_iron_butterflies(symbol, pool, strategies)
        self._try_call_butterflies(symbol, pool, strategies)
        self._try_put_butterflies(symbol, pool, strategies)
        self._try_short_call_butterflies(symbol, pool, strategies)
        self._try_short_put_butterflies(symbol, pool, strategies)
        self._try_call_condors(symbol, pool, strategies)
        self._try_put_condors(symbol, pool, strategies)

    def _try_box_spreads(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Box spread: bull call spread + bear put spread at same strikes/expiry.
        long call A + short call B + long put B + short put A (A < B)."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            long_calls = sorted([o for o in opts if o.is_long and o.is_call], key=lambda x: x.strike)
            short_calls = sorted([o for o in opts if o.is_short and o.is_call], key=lambda x: x.strike)

            for lc in long_calls:
                if lc.exhausted:
                    continue
                for sc in short_calls:
                    if sc.exhausted or sc.strike == lc.strike:
                        continue
                    low_strike = min(lc.strike, sc.strike)
                    high_strike = max(lc.strike, sc.strike)

                    # Find matching puts: long put at high strike, short put at low strike
                    lp = None
                    for o in opts:
                        if not o.exhausted and o.is_long and o.is_put and o.strike == high_strike:
                            lp = o
                            break
                    sp = None
                    for o in opts:
                        if not o.exhausted and o.is_short and o.is_put and o.strike == low_strike:
                            sp = o
                            break
                    if not lp or not sp:
                        continue

                    qty = min(lc.remaining, sc.remaining, lp.remaining, sp.remaining)
                    if qty <= ZERO:
                        continue

                    lc.consume(qty)
                    sc.consume(qty)
                    lp.consume(qty)
                    sp.consume(qty)
                    strategies.append(RecognizedStrategy(
                        strategy_id=_next_id("box_spread"),
                        strategy_type=StrategyType.BOX_SPREAD,
                        legs=[
                            StrategyLeg(position=lc.position.model_copy(update={"quantity": qty}), role="long_call", ratio=int(qty)),
                            StrategyLeg(position=sc.position.model_copy(update={"quantity": qty}), role="short_call", ratio=int(qty)),
                            StrategyLeg(position=lp.position.model_copy(update={"quantity": qty}), role="long_put", ratio=int(qty)),
                            StrategyLeg(position=sp.position.model_copy(update={"quantity": qty}), role="short_put", ratio=int(qty)),
                        ],
                        underlying_symbol=symbol,
                        description=f"Box spread: {low_strike}/{high_strike}",
                    ))

    def _try_iron_condors(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Iron condor: long OTM put + short put + short call + long OTM call, same expiry.
        Strikes: long_put < short_put < short_call < long_call."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            long_puts = sorted([o for o in opts if o.is_long and o.is_put], key=lambda x: x.strike)
            short_puts = sorted([o for o in opts if o.is_short and o.is_put], key=lambda x: x.strike)
            short_calls = sorted([o for o in opts if o.is_short and o.is_call], key=lambda x: x.strike)
            long_calls = sorted([o for o in opts if o.is_long and o.is_call], key=lambda x: x.strike)

            for sp in short_puts:
                if sp.exhausted:
                    continue
                for sc in short_calls:
                    if sc.exhausted or sc.strike <= sp.strike:
                        continue
                    # Find long put below short put
                    for lp in long_puts:
                        if lp.exhausted or lp.strike >= sp.strike:
                            continue
                        # Find long call above short call
                        for lc in long_calls:
                            if lc.exhausted or lc.strike <= sc.strike:
                                continue
                            # Must not be iron butterfly (short strikes must differ)
                            if sp.strike == sc.strike:
                                continue
                            qty = min(sp.remaining, sc.remaining, lp.remaining, lc.remaining)
                            if qty <= ZERO:
                                continue
                            sp.consume(qty)
                            sc.consume(qty)
                            lp.consume(qty)
                            lc.consume(qty)
                            strategies.append(RecognizedStrategy(
                                strategy_id=_next_id("iron_condor"),
                                strategy_type=StrategyType.IRON_CONDOR,
                                legs=[
                                    StrategyLeg(position=lp.position.model_copy(update={"quantity": qty}), role="long_put", ratio=int(qty)),
                                    StrategyLeg(position=sp.position.model_copy(update={"quantity": qty}), role="short_put", ratio=int(qty)),
                                    StrategyLeg(position=sc.position.model_copy(update={"quantity": qty}), role="short_call", ratio=int(qty)),
                                    StrategyLeg(position=lc.position.model_copy(update={"quantity": qty}), role="long_call", ratio=int(qty)),
                                ],
                                underlying_symbol=symbol,
                                description=f"Iron condor: {lp.strike}/{sp.strike}/{sc.strike}/{lc.strike}",
                            ))

    def _try_iron_butterflies(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Iron butterfly: long OTM put + short ATM put + short ATM call + long OTM call.
        Short put strike = short call strike."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            short_puts = [o for o in opts if o.is_short and o.is_put]
            short_calls = [o for o in opts if o.is_short and o.is_call]
            long_puts = sorted([o for o in opts if o.is_long and o.is_put], key=lambda x: x.strike)
            long_calls = sorted([o for o in opts if o.is_long and o.is_call], key=lambda x: x.strike)

            for sp in short_puts:
                if sp.exhausted:
                    continue
                for sc in short_calls:
                    if sc.exhausted or sp.strike != sc.strike:
                        continue
                    for lp in long_puts:
                        if lp.exhausted or lp.strike >= sp.strike:
                            continue
                        for lc in long_calls:
                            if lc.exhausted or lc.strike <= sc.strike:
                                continue
                            qty = min(sp.remaining, sc.remaining, lp.remaining, lc.remaining)
                            if qty <= ZERO:
                                continue
                            sp.consume(qty)
                            sc.consume(qty)
                            lp.consume(qty)
                            lc.consume(qty)
                            strategies.append(RecognizedStrategy(
                                strategy_id=_next_id("iron_butterfly"),
                                strategy_type=StrategyType.IRON_BUTTERFLY,
                                legs=[
                                    StrategyLeg(position=lp.position.model_copy(update={"quantity": qty}), role="long_put", ratio=int(qty)),
                                    StrategyLeg(position=sp.position.model_copy(update={"quantity": qty}), role="short_put", ratio=int(qty)),
                                    StrategyLeg(position=sc.position.model_copy(update={"quantity": qty}), role="short_call", ratio=int(qty)),
                                    StrategyLeg(position=lc.position.model_copy(update={"quantity": qty}), role="long_call", ratio=int(qty)),
                                ],
                                underlying_symbol=symbol,
                                description=f"Iron butterfly: {lp.strike}/{sp.strike}/{lc.strike}",
                            ))

    def _try_call_butterflies(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Long call butterfly: long 1 call (low) + short 2 calls (mid) + long 1 call (high).
        Strikes equidistant: high - mid = mid - low."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            long_calls = sorted([o for o in opts if o.is_long and o.is_call], key=lambda x: x.strike)
            short_calls = sorted([o for o in opts if o.is_short and o.is_call], key=lambda x: x.strike)

            for sc in short_calls:
                if sc.exhausted:
                    continue
                for lc_low in long_calls:
                    if lc_low.exhausted or lc_low.strike >= sc.strike:
                        continue
                    for lc_high in long_calls:
                        if lc_high is lc_low or lc_high.exhausted or lc_high.strike <= sc.strike:
                            continue
                        # Check equidistant
                        if (sc.strike - lc_low.strike) != (lc_high.strike - sc.strike):
                            continue
                        # Short needs 2x quantity
                        qty = min(lc_low.remaining, sc.remaining // 2, lc_high.remaining)
                        if qty <= ZERO:
                            continue
                        lc_low.consume(qty)
                        sc.consume(qty * 2)
                        lc_high.consume(qty)
                        strategies.append(RecognizedStrategy(
                            strategy_id=_next_id("long_call_butterfly"),
                            strategy_type=StrategyType.LONG_CALL_BUTTERFLY,
                            legs=[
                                StrategyLeg(position=lc_low.position.model_copy(update={"quantity": qty}), role="long_call_low", ratio=int(qty)),
                                StrategyLeg(position=sc.position.model_copy(update={"quantity": qty * 2}), role="short_call_mid", ratio=int(qty * 2)),
                                StrategyLeg(position=lc_high.position.model_copy(update={"quantity": qty}), role="long_call_high", ratio=int(qty)),
                            ],
                            underlying_symbol=symbol,
                            description=f"Long call butterfly: {lc_low.strike}/{sc.strike}/{lc_high.strike}",
                        ))

    def _try_put_butterflies(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Long put butterfly: long 1 put (high) + short 2 puts (mid) + long 1 put (low)."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            long_puts = sorted([o for o in opts if o.is_long and o.is_put], key=lambda x: x.strike)
            short_puts = sorted([o for o in opts if o.is_short and o.is_put], key=lambda x: x.strike)

            for sp in short_puts:
                if sp.exhausted:
                    continue
                for lp_low in long_puts:
                    if lp_low.exhausted or lp_low.strike >= sp.strike:
                        continue
                    for lp_high in long_puts:
                        if lp_high is lp_low or lp_high.exhausted or lp_high.strike <= sp.strike:
                            continue
                        if (sp.strike - lp_low.strike) != (lp_high.strike - sp.strike):
                            continue
                        qty = min(lp_low.remaining, sp.remaining // 2, lp_high.remaining)
                        if qty <= ZERO:
                            continue
                        lp_low.consume(qty)
                        sp.consume(qty * 2)
                        lp_high.consume(qty)
                        strategies.append(RecognizedStrategy(
                            strategy_id=_next_id("long_put_butterfly"),
                            strategy_type=StrategyType.LONG_PUT_BUTTERFLY,
                            legs=[
                                StrategyLeg(position=lp_low.position.model_copy(update={"quantity": qty}), role="long_put_low", ratio=int(qty)),
                                StrategyLeg(position=sp.position.model_copy(update={"quantity": qty * 2}), role="short_put_mid", ratio=int(qty * 2)),
                                StrategyLeg(position=lp_high.position.model_copy(update={"quantity": qty}), role="long_put_high", ratio=int(qty)),
                            ],
                            underlying_symbol=symbol,
                            description=f"Long put butterfly: {lp_low.strike}/{sp.strike}/{lp_high.strike}",
                        ))

    def _try_short_call_butterflies(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Short call butterfly: short 1 call (low) + long 2 calls (mid) + short 1 call (high).
        Strikes equidistant: high - mid = mid - low."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            short_calls = sorted([o for o in opts if o.is_short and o.is_call], key=lambda x: x.strike)
            long_calls = sorted([o for o in opts if o.is_long and o.is_call], key=lambda x: x.strike)

            for lc_mid in long_calls:
                if lc_mid.exhausted or lc_mid.remaining < 2:
                    continue
                for sc_low in short_calls:
                    if sc_low.exhausted or sc_low.strike >= lc_mid.strike:
                        continue
                    expected_high = lc_mid.strike + (lc_mid.strike - sc_low.strike)
                    for sc_high in short_calls:
                        if sc_high is sc_low or sc_high.exhausted:
                            continue
                        if sc_high.strike != expected_high:
                            continue
                        qty = min(sc_low.remaining, lc_mid.remaining // 2, sc_high.remaining)
                        if qty <= ZERO:
                            continue
                        sc_low.consume(qty)
                        lc_mid.consume(qty * 2)
                        sc_high.consume(qty)
                        strategies.append(RecognizedStrategy(
                            strategy_id=_next_id("short_call_butterfly"),
                            strategy_type=StrategyType.SHORT_CALL_BUTTERFLY,
                            legs=[
                                StrategyLeg(position=sc_low.position.model_copy(update={"quantity": qty}), role="short_call_low", ratio=int(qty)),
                                StrategyLeg(position=lc_mid.position.model_copy(update={"quantity": qty * 2}), role="long_call_mid", ratio=int(qty * 2)),
                                StrategyLeg(position=sc_high.position.model_copy(update={"quantity": qty}), role="short_call_high", ratio=int(qty)),
                            ],
                            underlying_symbol=symbol,
                            description=f"Short call butterfly: {sc_low.strike}/{lc_mid.strike}/{sc_high.strike}",
                        ))

    def _try_short_put_butterflies(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Short put butterfly: short 1 put (low) + long 2 puts (mid) + short 1 put (high).
        Strikes equidistant: high - mid = mid - low."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            short_puts = sorted([o for o in opts if o.is_short and o.is_put], key=lambda x: x.strike)
            long_puts = sorted([o for o in opts if o.is_long and o.is_put], key=lambda x: x.strike)

            for lp_mid in long_puts:
                if lp_mid.exhausted or lp_mid.remaining < 2:
                    continue
                for sp_low in short_puts:
                    if sp_low.exhausted or sp_low.strike >= lp_mid.strike:
                        continue
                    expected_high = lp_mid.strike + (lp_mid.strike - sp_low.strike)
                    for sp_high in short_puts:
                        if sp_high is sp_low or sp_high.exhausted:
                            continue
                        if sp_high.strike != expected_high:
                            continue
                        qty = min(sp_low.remaining, lp_mid.remaining // 2, sp_high.remaining)
                        if qty <= ZERO:
                            continue
                        sp_low.consume(qty)
                        lp_mid.consume(qty * 2)
                        sp_high.consume(qty)
                        strategies.append(RecognizedStrategy(
                            strategy_id=_next_id("short_put_butterfly"),
                            strategy_type=StrategyType.SHORT_PUT_BUTTERFLY,
                            legs=[
                                StrategyLeg(position=sp_low.position.model_copy(update={"quantity": qty}), role="short_put_low", ratio=int(qty)),
                                StrategyLeg(position=lp_mid.position.model_copy(update={"quantity": qty * 2}), role="long_put_mid", ratio=int(qty * 2)),
                                StrategyLeg(position=sp_high.position.model_copy(update={"quantity": qty}), role="short_put_high", ratio=int(qty)),
                            ],
                            underlying_symbol=symbol,
                            description=f"Short put butterfly: {sp_low.strike}/{lp_mid.strike}/{sp_high.strike}",
                        ))

    def _try_call_condors(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Long call condor: long call A + short call B + short call C + long call D.
        Strikes: A < B < C < D, all same expiry."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            long_calls = sorted([o for o in opts if o.is_long and o.is_call], key=lambda x: x.strike)
            short_calls = sorted([o for o in opts if o.is_short and o.is_call], key=lambda x: x.strike)

            for lc_a in long_calls:
                if lc_a.exhausted:
                    continue
                for sc_b in short_calls:
                    if sc_b.exhausted or sc_b.strike <= lc_a.strike:
                        continue
                    for sc_c in short_calls:
                        if sc_c is sc_b or sc_c.exhausted or sc_c.strike <= sc_b.strike:
                            continue
                        for lc_d in long_calls:
                            if lc_d is lc_a or lc_d.exhausted or lc_d.strike <= sc_c.strike:
                                continue
                            qty = min(lc_a.remaining, sc_b.remaining, sc_c.remaining, lc_d.remaining)
                            if qty <= ZERO:
                                continue
                            lc_a.consume(qty)
                            sc_b.consume(qty)
                            sc_c.consume(qty)
                            lc_d.consume(qty)
                            strategies.append(RecognizedStrategy(
                                strategy_id=_next_id("long_call_condor"),
                                strategy_type=StrategyType.LONG_CALL_CONDOR,
                                legs=[
                                    StrategyLeg(position=lc_a.position.model_copy(update={"quantity": qty}), role="long_call_low", ratio=int(qty)),
                                    StrategyLeg(position=sc_b.position.model_copy(update={"quantity": qty}), role="short_call_mid_low", ratio=int(qty)),
                                    StrategyLeg(position=sc_c.position.model_copy(update={"quantity": qty}), role="short_call_mid_high", ratio=int(qty)),
                                    StrategyLeg(position=lc_d.position.model_copy(update={"quantity": qty}), role="long_call_high", ratio=int(qty)),
                                ],
                                underlying_symbol=symbol,
                                description=f"Long call condor: {lc_a.strike}/{sc_b.strike}/{sc_c.strike}/{lc_d.strike}",
                            ))

    def _try_put_condors(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Long put condor: long put A + short put B + short put C + long put D.
        Strikes: A < B < C < D, all same expiry."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            long_puts = sorted([o for o in opts if o.is_long and o.is_put], key=lambda x: x.strike)
            short_puts = sorted([o for o in opts if o.is_short and o.is_put], key=lambda x: x.strike)

            for lp_a in long_puts:
                if lp_a.exhausted:
                    continue
                for sp_b in short_puts:
                    if sp_b.exhausted or sp_b.strike <= lp_a.strike:
                        continue
                    for sp_c in short_puts:
                        if sp_c is sp_b or sp_c.exhausted or sp_c.strike <= sp_b.strike:
                            continue
                        for lp_d in long_puts:
                            if lp_d is lp_a or lp_d.exhausted or lp_d.strike <= sp_c.strike:
                                continue
                            qty = min(lp_a.remaining, sp_b.remaining, sp_c.remaining, lp_d.remaining)
                            if qty <= ZERO:
                                continue
                            lp_a.consume(qty)
                            sp_b.consume(qty)
                            sp_c.consume(qty)
                            lp_d.consume(qty)
                            strategies.append(RecognizedStrategy(
                                strategy_id=_next_id("long_put_condor"),
                                strategy_type=StrategyType.LONG_PUT_CONDOR,
                                legs=[
                                    StrategyLeg(position=lp_a.position.model_copy(update={"quantity": qty}), role="long_put_low", ratio=int(qty)),
                                    StrategyLeg(position=sp_b.position.model_copy(update={"quantity": qty}), role="short_put_mid_low", ratio=int(qty)),
                                    StrategyLeg(position=sp_c.position.model_copy(update={"quantity": qty}), role="short_put_mid_high", ratio=int(qty)),
                                    StrategyLeg(position=lp_d.position.model_copy(update={"quantity": qty}), role="long_put_high", ratio=int(qty)),
                                ],
                                underlying_symbol=symbol,
                                description=f"Long put condor: {lp_a.strike}/{sp_b.strike}/{sp_c.strike}/{lp_d.strike}",
                            ))

    # ================================================================
    # Ratio spreads (unequal leg quantities)
    # ================================================================

    def _recognize_ratio_spreads(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Ratio spreads and backspreads: same type, same expiry, different strikes,
        unequal quantities."""
        self._try_ratio_for_type(symbol, pool, strategies, is_call=True)
        self._try_ratio_for_type(symbol, pool, strategies, is_call=False)

    def _try_ratio_for_type(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
        is_call: bool,
    ) -> None:
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            if is_call:
                longs = sorted([o for o in opts if o.is_long and o.is_call], key=lambda x: x.strike)
                shorts = sorted([o for o in opts if o.is_short and o.is_call], key=lambda x: x.strike)
            else:
                longs = sorted([o for o in opts if o.is_long and o.is_put], key=lambda x: x.strike)
                shorts = sorted([o for o in opts if o.is_short and o.is_put], key=lambda x: x.strike)

            for lo in longs:
                if lo.exhausted:
                    continue
                for so in shorts:
                    if so.exhausted or so.strike == lo.strike:
                        continue
                    # Only match as ratio if quantities differ
                    if lo.remaining == so.remaining:
                        continue

                    long_qty = lo.remaining
                    short_qty = so.remaining

                    if short_qty > long_qty:
                        # Front ratio spread: more short than long
                        if is_call:
                            stype = StrategyType.RATIO_CALL_SPREAD
                        else:
                            stype = StrategyType.RATIO_PUT_SPREAD
                    else:
                        # Backspread: more long than short
                        if is_call:
                            stype = StrategyType.CALL_BACKSPREAD
                        else:
                            stype = StrategyType.PUT_BACKSPREAD

                    lo.consume(long_qty)
                    so.consume(short_qty)
                    strategies.append(RecognizedStrategy(
                        strategy_id=_next_id("ratio_spread"),
                        strategy_type=stype,
                        legs=[
                            StrategyLeg(position=lo.position.model_copy(update={"quantity": long_qty}), role="long_leg", ratio=int(long_qty)),
                            StrategyLeg(position=so.position.model_copy(update={"quantity": short_qty}), role="short_leg", ratio=int(short_qty)),
                        ],
                        underlying_symbol=symbol,
                        description=f"{stype.value}: {lo.strike}/{so.strike} ({int(long_qty)}x{int(short_qty)})",
                    ))

    # ================================================================
    # Synthetics (long call + short put or short call + long put, same strike/expiry)
    # ================================================================

    def _try_synthetics(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Synthetic long: long call + short put, same strike/expiry.
        Synthetic short: short call + long put, same strike/expiry."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            # Synthetic long: long call + short put
            long_calls = [o for o in opts if o.is_long and o.is_call]
            short_puts = [o for o in opts if o.is_short and o.is_put]
            for lc in long_calls:
                if lc.exhausted:
                    continue
                for sp in short_puts:
                    if sp.exhausted or sp.strike != lc.strike:
                        continue
                    qty = min(lc.remaining, sp.remaining)
                    if qty <= ZERO:
                        continue
                    lc.consume(qty)
                    sp.consume(qty)
                    strategies.append(RecognizedStrategy(
                        strategy_id=_next_id("synthetic_long"),
                        strategy_type=StrategyType.SYNTHETIC_LONG,
                        legs=[
                            StrategyLeg(position=lc.position.model_copy(update={"quantity": qty}), role="long_call", ratio=int(qty)),
                            StrategyLeg(position=sp.position.model_copy(update={"quantity": qty}), role="short_put", ratio=int(qty)),
                        ],
                        underlying_symbol=symbol,
                        description=f"Synthetic long: {lc.strike} strike",
                    ))

            # Synthetic short: short call + long put
            short_calls = [o for o in opts if o.is_short and o.is_call]
            long_puts = [o for o in opts if o.is_long and o.is_put]
            for sc in short_calls:
                if sc.exhausted:
                    continue
                for lp in long_puts:
                    if lp.exhausted or lp.strike != sc.strike:
                        continue
                    qty = min(sc.remaining, lp.remaining)
                    if qty <= ZERO:
                        continue
                    sc.consume(qty)
                    lp.consume(qty)
                    strategies.append(RecognizedStrategy(
                        strategy_id=_next_id("synthetic_short"),
                        strategy_type=StrategyType.SYNTHETIC_SHORT,
                        legs=[
                            StrategyLeg(position=sc.position.model_copy(update={"quantity": qty}), role="short_call", ratio=int(qty)),
                            StrategyLeg(position=lp.position.model_copy(update={"quantity": qty}), role="long_put", ratio=int(qty)),
                        ],
                        underlying_symbol=symbol,
                        description=f"Synthetic short: {sc.strike} strike",
                    ))

    # ================================================================
    # 2-leg same expiry strategies
    # ================================================================

    def _recognize_two_leg_same_expiry(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        # Try straddles first (same strike), then strangles, then verticals
        self._try_straddles(symbol, pool, strategies)
        self._try_strangles(symbol, pool, strategies)
        self._try_vertical_spreads(symbol, pool, strategies)

    def _try_vertical_spreads(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Vertical spreads: same type, same expiry, different strikes."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            # Call verticals
            long_calls = sorted([o for o in opts if o.is_long and o.is_call], key=lambda x: x.strike)
            short_calls = sorted([o for o in opts if o.is_short and o.is_call], key=lambda x: x.strike)
            self._match_verticals_calls(symbol, long_calls, short_calls, strategies)

            # Put verticals
            long_puts = sorted([o for o in opts if o.is_long and o.is_put], key=lambda x: x.strike)
            short_puts = sorted([o for o in opts if o.is_short and o.is_put], key=lambda x: x.strike)
            self._match_verticals_puts(symbol, long_puts, short_puts, strategies)

    def _match_verticals_calls(
        self,
        symbol: str,
        long_calls: list[_PoolEntry],
        short_calls: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        for lc in long_calls:
            if lc.exhausted:
                continue
            for sc in short_calls:
                if sc.exhausted or lc.strike == sc.strike:
                    continue
                qty = min(lc.remaining, sc.remaining)
                if qty <= ZERO:
                    continue

                if lc.strike < sc.strike:
                    # Bull call spread (debit): long lower, short higher
                    stype = StrategyType.BULL_CALL_SPREAD
                    desc = f"Bull call spread: {lc.strike}/{sc.strike}"
                else:
                    # Bear call spread (credit): short lower, long higher
                    stype = StrategyType.BEAR_CALL_SPREAD
                    desc = f"Bear call spread: {sc.strike}/{lc.strike}"

                lc.consume(qty)
                sc.consume(qty)
                strategies.append(RecognizedStrategy(
                    strategy_id=_next_id("vertical"),
                    strategy_type=stype,
                    legs=[
                        StrategyLeg(position=lc.position.model_copy(update={"quantity": qty}), role="long_call", ratio=int(qty)),
                        StrategyLeg(position=sc.position.model_copy(update={"quantity": qty}), role="short_call", ratio=int(qty)),
                    ],
                    underlying_symbol=symbol,
                    description=desc,
                ))

    def _match_verticals_puts(
        self,
        symbol: str,
        long_puts: list[_PoolEntry],
        short_puts: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        for lp in long_puts:
            if lp.exhausted:
                continue
            for sp in short_puts:
                if sp.exhausted or lp.strike == sp.strike:
                    continue
                qty = min(lp.remaining, sp.remaining)
                if qty <= ZERO:
                    continue

                if sp.strike > lp.strike:
                    # Bull put spread (credit): short higher, long lower
                    stype = StrategyType.BULL_PUT_SPREAD
                    desc = f"Bull put spread: {lp.strike}/{sp.strike}"
                else:
                    # Bear put spread (debit): long higher, short lower
                    stype = StrategyType.BEAR_PUT_SPREAD
                    desc = f"Bear put spread: {sp.strike}/{lp.strike}"

                lp.consume(qty)
                sp.consume(qty)
                strategies.append(RecognizedStrategy(
                    strategy_id=_next_id("vertical"),
                    strategy_type=stype,
                    legs=[
                        StrategyLeg(position=lp.position.model_copy(update={"quantity": qty}), role="long_put", ratio=int(qty)),
                        StrategyLeg(position=sp.position.model_copy(update={"quantity": qty}), role="short_put", ratio=int(qty)),
                    ],
                    underlying_symbol=symbol,
                    description=desc,
                ))

    def _try_straddles(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Straddle: same strike, same expiry, one call + one put, same side."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            # Long straddle: long call + long put, same strike
            long_calls = [o for o in opts if o.is_long and o.is_call]
            long_puts = [o for o in opts if o.is_long and o.is_put]
            for lc in long_calls:
                if lc.exhausted:
                    continue
                for lp in long_puts:
                    if lp.exhausted or lc.strike != lp.strike:
                        continue
                    qty = min(lc.remaining, lp.remaining)
                    if qty <= ZERO:
                        continue
                    lc.consume(qty)
                    lp.consume(qty)
                    strategies.append(RecognizedStrategy(
                        strategy_id=_next_id("long_straddle"),
                        strategy_type=StrategyType.LONG_STRADDLE,
                        legs=[
                            StrategyLeg(position=lc.position.model_copy(update={"quantity": qty}), role="long_call", ratio=int(qty)),
                            StrategyLeg(position=lp.position.model_copy(update={"quantity": qty}), role="long_put", ratio=int(qty)),
                        ],
                        underlying_symbol=symbol,
                        description=f"Long straddle: {lc.strike} strike",
                    ))

            # Short straddle: short call + short put, same strike
            short_calls = [o for o in opts if o.is_short and o.is_call]
            short_puts = [o for o in opts if o.is_short and o.is_put]
            for sc in short_calls:
                if sc.exhausted:
                    continue
                for sp in short_puts:
                    if sp.exhausted or sc.strike != sp.strike:
                        continue
                    qty = min(sc.remaining, sp.remaining)
                    if qty <= ZERO:
                        continue
                    sc.consume(qty)
                    sp.consume(qty)
                    strategies.append(RecognizedStrategy(
                        strategy_id=_next_id("short_straddle"),
                        strategy_type=StrategyType.SHORT_STRADDLE,
                        legs=[
                            StrategyLeg(position=sc.position.model_copy(update={"quantity": qty}), role="short_call", ratio=int(qty)),
                            StrategyLeg(position=sp.position.model_copy(update={"quantity": qty}), role="short_put", ratio=int(qty)),
                        ],
                        underlying_symbol=symbol,
                        description=f"Short straddle: {sc.strike} strike",
                    ))

    def _try_strangles(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Strangle: same expiry, different strikes, one call + one put, same side."""
        available = [o for o in pool if not o.exhausted]
        by_expiry = self._group_by_expiry(available)

        for expiry, opts in by_expiry.items():
            # Long strangle: long put (lower) + long call (higher)
            long_calls = sorted([o for o in opts if o.is_long and o.is_call], key=lambda x: x.strike)
            long_puts = sorted([o for o in opts if o.is_long and o.is_put], key=lambda x: x.strike)
            for lp in long_puts:
                if lp.exhausted:
                    continue
                for lc in long_calls:
                    if lc.exhausted or lc.strike <= lp.strike:
                        continue
                    qty = min(lc.remaining, lp.remaining)
                    if qty <= ZERO:
                        continue
                    lc.consume(qty)
                    lp.consume(qty)
                    strategies.append(RecognizedStrategy(
                        strategy_id=_next_id("long_strangle"),
                        strategy_type=StrategyType.LONG_STRANGLE,
                        legs=[
                            StrategyLeg(position=lp.position.model_copy(update={"quantity": qty}), role="long_put", ratio=int(qty)),
                            StrategyLeg(position=lc.position.model_copy(update={"quantity": qty}), role="long_call", ratio=int(qty)),
                        ],
                        underlying_symbol=symbol,
                        description=f"Long strangle: {lp.strike}/{lc.strike}",
                    ))

            # Short strangle: short put (lower) + short call (higher)
            short_calls = sorted([o for o in opts if o.is_short and o.is_call], key=lambda x: x.strike)
            short_puts = sorted([o for o in opts if o.is_short and o.is_put], key=lambda x: x.strike)
            for sp in short_puts:
                if sp.exhausted:
                    continue
                for sc in short_calls:
                    if sc.exhausted or sc.strike <= sp.strike:
                        continue
                    qty = min(sc.remaining, sp.remaining)
                    if qty <= ZERO:
                        continue
                    sc.consume(qty)
                    sp.consume(qty)
                    strategies.append(RecognizedStrategy(
                        strategy_id=_next_id("short_strangle"),
                        strategy_type=StrategyType.SHORT_STRANGLE,
                        legs=[
                            StrategyLeg(position=sp.position.model_copy(update={"quantity": qty}), role="short_put", ratio=int(qty)),
                            StrategyLeg(position=sc.position.model_copy(update={"quantity": qty}), role="short_call", ratio=int(qty)),
                        ],
                        underlying_symbol=symbol,
                        description=f"Short strangle: {sp.strike}/{sc.strike}",
                    ))

    # ================================================================
    # 2-leg different expiry strategies
    # ================================================================

    def _recognize_two_leg_diff_expiry(
        self,
        symbol: str,
        pool: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Calendar/diagonal spreads: same type, different expiry."""
        available = [o for o in pool if not o.exhausted]
        if len(available) < 2:
            return

        # Group by option type
        calls = [o for o in available if o.is_call]
        puts = [o for o in available if o.is_put]

        self._try_calendar_diagonal(symbol, calls, strategies)
        self._try_calendar_diagonal(symbol, puts, strategies)

    def _try_calendar_diagonal(
        self,
        symbol: str,
        options: list[_PoolEntry],
        strategies: list[RecognizedStrategy],
    ) -> None:
        """Match calendar (same strike) or diagonal (different strike) spreads.
        Long far + short near."""
        for o1 in options:
            if o1.exhausted:
                continue
            for o2 in options:
                if o2 is o1 or o2.exhausted:
                    continue
                if o1.expiry == o2.expiry:
                    continue
                # Determine which is long far and which is short near
                if o1.is_long and o2.is_short and o1.expiry > o2.expiry:
                    long_far, short_near = o1, o2
                elif o2.is_long and o1.is_short and o2.expiry > o1.expiry:
                    long_far, short_near = o2, o1
                else:
                    continue

                qty = min(long_far.remaining, short_near.remaining)
                if qty <= ZERO:
                    continue

                if long_far.strike == short_near.strike:
                    stype = StrategyType.CALENDAR_SPREAD
                    desc = f"Calendar spread: {long_far.strike} {short_near.option_type.value}"
                else:
                    stype = StrategyType.DIAGONAL_SPREAD
                    desc = f"Diagonal spread: {short_near.strike}/{long_far.strike} {long_far.option_type.value}"

                long_far.consume(qty)
                short_near.consume(qty)
                strategies.append(RecognizedStrategy(
                    strategy_id=_next_id("time_spread"),
                    strategy_type=stype,
                    legs=[
                        StrategyLeg(position=long_far.position.model_copy(update={"quantity": qty}), role="long_far", ratio=int(qty)),
                        StrategyLeg(position=short_near.position.model_copy(update={"quantity": qty}), role="short_near", ratio=int(qty)),
                    ],
                    underlying_symbol=symbol,
                    description=desc,
                ))

    # ================================================================
    # Helpers
    # ================================================================

    @staticmethod
    def _group_by_expiry(entries: list[_PoolEntry]) -> dict[date, list[_PoolEntry]]:
        groups: dict[date, list[_PoolEntry]] = defaultdict(list)
        for e in entries:
            if not e.exhausted:
                groups[e.expiry].append(e)
        return dict(groups)
