from netstate_reconciler.mcp_client import MCPToolbox, ToolDescriptor, normalize_mcp_result, result_failed


class FakeClient:
    def __init__(self):
        self.last = None

    def call_tool(self, name, arguments=None):
        self.last = (name, arguments)
        return {"isError": False, "content": [{"type": "text", "text": "ok"}]}

    def list_tools(self):
        return []


def test_normalize_mcp_text_and_error():
    normalized = normalize_mcp_result({"isError": True, "content": [{"type": "text", "text": "Command failed"}]})
    assert normalized["text"] == "Command failed"
    assert result_failed(normalized)


def test_toolbox_maps_semantic_arguments_from_schema():
    client = FakeClient()
    toolbox = MCPToolbox(client)
    toolbox.catalog["pt_verify_connectivity"] = ToolDescriptor(
        name="pt_verify_connectivity", description="ping",
        schema={"type": "object", "properties": {"from_device": {"type": "string"}, "to_ip": {"type": "string"}}, "required": ["from_device", "to_ip"]},
    )
    toolbox.invoke("pt_verify_connectivity", {"from_device": "PC1", "to_ip": "192.168.1.1"})
    assert client.last == ("pt_verify_connectivity", {"from_device": "PC1", "to_ip": "192.168.1.1"})
