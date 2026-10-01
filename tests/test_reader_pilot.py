from preprocessing.reader_pilot import repetition_detected


def test_repeated_spans_stop_after_three_copies():
    span = list(range(31))
    assert repetition_detected(span * 3) == 31
    assert repetition_detected(span * 2) is None


def test_distinct_output_does_not_trigger():
    assert repetition_detected(list(range(1000))) is None
