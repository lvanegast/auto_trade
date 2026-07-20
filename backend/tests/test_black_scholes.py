import datetime
from src.strategy.polymarket_spot_arb import PolymarketSpotArbStrategy, phi


def test_normal_cdf():
    # phi(0) = 0.5
    assert abs(phi(0.0) - 0.5) < 1e-5
    # phi(1.96) ~= 0.975
    assert abs(phi(1.96) - 0.975) < 1e-3


def test_black_scholes_deep_in_the_money():
    exp_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=10
    )
    strategy = PolymarketSpotArbStrategy(
        symbol="BTC_TEST",
        strike_price=50000.0,
        expiration_time=exp_time,
        volatility=0.30,
    )

    # Spot = 70,000 >> Strike = 50,000 -> Probabilidad teórica cercana a 1.0 (99%)
    prob = strategy.calculate_theoretical_probability(70000.0)
    assert prob > 0.95


def test_black_scholes_deep_out_of_the_money():
    exp_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=10
    )
    strategy = PolymarketSpotArbStrategy(
        symbol="BTC_TEST",
        strike_price=80000.0,
        expiration_time=exp_time,
        volatility=0.30,
    )

    # Spot = 50,000 << Strike = 80,000 -> Probabilidad teórica cercana a 0.0 (1%)
    prob = strategy.calculate_theoretical_probability(50000.0)
    assert prob < 0.05
