import commentary_engine


def test_disabled_commentary_never_constructs_or_calls_api_client(monkeypatch, tmp_path):
    client_constructions = []

    def unexpected_client_construction():
        client_constructions.append(True)
        raise AssertionError("disabled commentary must not construct an OpenAI client")

    monkeypatch.setattr(commentary_engine, "OpenAI", unexpected_client_construction)
    engine = commentary_engine.CommentaryEngine(output_dir=tmp_path, enabled=False)
    state = {"player_cards": ["10h", "7s"], "dealer_cards": ["9d"]}

    assert engine.client is None
    assert engine.should_comment(state) is False
    assert engine.generate_text_comment(state) is None
    assert engine._get_embedding("test") is None
    assert engine.generate_audio("test") is None
    assert engine.process_state(state) is None
    assert engine.process_state_non_blocking(state) is None
    assert client_constructions == []
