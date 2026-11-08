from app.services.ratelimit import RateLimiter


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_limit_and_window():
    clock = Clock()
    rl = RateLimiter(limit=2, window=10, clock=clock)
    assert rl.allow("a") and rl.allow("a")
    assert not rl.allow("a")
    assert rl.allow("b")
    clock.t = 10
    assert rl.allow("a")


def test_reset():
    rl = RateLimiter(limit=1, window=100)
    assert rl.allow("a") and not rl.allow("a")
    rl.reset()
    assert rl.allow("a")
