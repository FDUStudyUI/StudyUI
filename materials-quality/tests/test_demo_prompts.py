from materials_quality.demos.catalog import list_datasets


def test_demo_prompts_are_conversational():
    prompts = [item["prompt"] for item in list_datasets()]
    assert len(prompts) == 5
    assert all("{path}" in prompt for prompt in prompts)
    assert all(
        any(marker in prompt for marker in ("请", "帮我", "麻烦", "我想", "这是")) for prompt in prompts
    )
    assert all("请分析文件 {path}" not in prompt for prompt in prompts)
