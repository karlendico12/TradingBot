
class RiskManager:
    @staticmethod
    def position_size(balance, risk_percent, entry, stop):
        risk_amount = balance * (risk_percent / 100)
        distance = abs(entry - stop)
        if distance == 0:
            return 0
        return round(risk_amount / distance, 3)

    @staticmethod
    def take_profit(entry, stop, rr=2):
        distance = abs(entry - stop)
        if entry > stop:
            return entry + distance * rr
        return entry - distance * rr
