from research.costs import CostModel


def test_cost_model_applies_slippage_commission_and_sell_tax():
    model = CostModel(commission_rate=0.001, tax_rate=0.002, slippage_bps=10)

    buy = model.estimate("buy", price=100.0, quantity=10)
    sell = model.estimate("sell", price=100.0, quantity=10)

    assert buy.fill_price == 100.1
    assert buy.commission == 1.001
    assert buy.tax == 0.0
    assert buy.cash_delta == -1002.001

    assert sell.fill_price == 99.9
    assert sell.commission == 0.999
    assert sell.tax == 1.998
    assert sell.cash_delta == 996.003
