from finagent.clients import N_CLIENTS, make_clients


def test_clients_are_deterministic_fictional_and_have_unique_canaries():
    a, b = make_clients(), make_clients()
    assert a == b and len(a) == N_CLIENTS
    assert len({c["canary"] for c in a}) == N_CLIENTS
    for c in a:
        assert c["display_name"].startswith("Client ") and c["canary"] in c["notes"]
        assert sum(c["allocation"].values()) == 100 and min(c["allocation"].values()) >= 0
