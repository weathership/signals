from signals.engine.queue_merge import merge_queue_hints


def test_merge_adds_missing_light() -> None:
    doc = {
        "partitions": [
            {
                "name": "default",
                "queues": [
                    {
                        "name": "root",
                        "queues": [
                            {
                                "name": "internal",
                                "queues": [
                                    {
                                        "name": "inference",
                                        "queues": [
                                            {"name": "extract", "maxapplications": 16},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    _, added = merge_queue_hints(
        doc,
        [
            {
                "path": "root.internal.inference.light",
                "resource_class": "internal.inference.light",
                "gpu_guarantee": 1,
                "gpu_max": 2,
                "max_applications": 2,
            }
        ],
    )
    assert added == ["root.internal.inference.light"]
    _, again = merge_queue_hints(
        doc, [{"path": "root.internal.inference.light", "gpu_guarantee": 1}]
    )
    assert again == []
