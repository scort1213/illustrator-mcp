import subprocess
import tempfile
import os
import asyncio
import base64
import io
import logging
import time
import json
import sys

try:
    from . import safety
    from .guard import wrap, STATE_SCRIPT
except ImportError:
    import safety
    from guard import wrap, STATE_SCRIPT
import mcp.types as types
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

try:
    from .prompt import (
        get_system_prompt,
        get_prompt_suggestions,
        get_advanced_templates,
        get_prompting_tips,
        display_help,
        format_advanced_template,
    )
except ImportError:
    from prompt import (
        get_system_prompt,
        get_prompt_suggestions,
        get_advanced_templates,
        get_prompting_tips,
        display_help,
        format_advanced_template,
    )

try:
    from .platform_backend import get_backend
except ImportError:
    from platform_backend import get_backend

# Set up logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

server = Server("illustrator")

# Initialise the platform-specific backend (Windows COM or macOS AppleScript).
# This is done lazily on first tool call to avoid errors at import time when
# Illustrator is not yet running.
_backend = None


def _get_backend():
    global _backend
    if _backend is None:
        _backend = get_backend()
    return _backend


def _print_client_config_hint() -> None:
    """Print a ready-to-copy config snippet for MCP clients."""
    python_path = sys.executable.replace("\\", "\\\\")
    server_path = os.path.abspath(__file__).replace("\\", "\\\\")
    hint = f"""
Add this MCP config in your client settings (Claude Desktop / Claude Code / Cursor / VS Code Copilot / JetBrains Copilot):
{{
  "mcpServers": {{
    "illustrator": {{
      "command": "{python_path}",
      "args": [
        "{server_path}"
      ]
    }}
  }}
}}
"""
    print(hint, file=sys.stderr)
    sys.stderr.flush()

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    logging.info("Listing available tools.")
    return [
        types.Tool(name="get_state", description="Read Illustrator version and open document paths/counts without editing.", inputSchema={"type":"object","properties":{}}),
        types.Tool(name="recover_connection", description="After inspecting get_state, acknowledge partial changes and unlock writes. Does not undo or retry.", inputSchema={"type":"object","properties":{"acknowledge":{"type":"boolean"}},"required":["acknowledge"]}),
        types.Tool(
            name="view",
            description="View a screenshot of the Adobe Illustrator window",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="run",
            description="Run ExtendScript code in Illustrator",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "minLength":1, "description": "Trusted ExtendScript code; not sandboxed."},
                    "target_path": {"type":"string", "description":"Full path of an open saved document; required when several documents are open."},
                    "timeout_seconds": {"type":"number", "exclusiveMinimum":0, "maximum":120, "default":30}
                },
                "required": ["code"],
            },
        ),
        types.Tool(
            name="get_prompt_suggestions",
            description="Get categorized prompt suggestions for creating content in Illustrator",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional: Filter by category (e.g., 'logos', 'illustrations', 'icons')",
                        "enum": [
                            "basic_shapes",
                            "typography",
                            "logos",
                            "illustrations", 
                            "icons",
                            "artistic",
                            "charts",
                            "print"
                        ]
                    }
                }
            },
        ),
        types.Tool(
            name="get_system_prompt",
            description="Get the system prompt template for better AI guidance when working with Illustrator",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_prompting_tips",
            description="Get tips for creating better prompts when working with Illustrator",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_advanced_template",
            description="Get an advanced prompt template for complex design tasks",
            inputSchema={
                "type": "object",
                "properties": {
                    "template_type": {
                        "type": "string",
                        "description": "Type of template to get",
                        "enum": ["logo_design", "illustration", "infographic", "icon_set"]
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Parameters to fill in the template (varies by template type)"
                    }
                },
                "required": ["template_type"]
            },
        ),
        types.Tool(
            name="help",
            description="Display comprehensive help information for using the Illustrator MCP server",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]

def capture_illustrator() -> list[types.TextContent | types.ImageContent]:
    logging.info("Starting screenshot capture for Illustrator.")
    try:
        backend = _get_backend()
        screenshot_data = backend.capture_screenshot()
        logging.info("Screenshot captured successfully.")
        return [types.ImageContent(type="image", mimeType="image/jpeg", data=screenshot_data)]
    except Exception as e:
        logging.error(f"Failed to capture screenshot: {str(e)}")
        return [types.TextContent(type="text", text=f"Failed to capture screenshot: {str(e)}")]

def run_illustrator_script(code: str) -> list[types.TextContent]:
    logging.info("Running ExtendScript code in Illustrator.")
    try:
        backend = _get_backend()
        result = backend.run_script(code)
        logging.info("ExtendScript executed successfully.")
        return [types.TextContent(type="text", text=result)]
    except Exception as e:
        logging.error(f"Failed to execute script: {str(e)}")
        return [types.TextContent(type="text", text=f"Failed to execute script: {str(e)}")]

async def _handle_call_tool(name: str, arguments: dict | None):
    logging.info("Received tool call: %s", name)
    
    if name in ("get_state", "recover_connection"):
        recover = name == "recover_connection"
        if recover and (not arguments or arguments.get("acknowledge") is not True):
            raise ValueError("invalid_argument: acknowledge must be true after inspecting state")
        def read_state():
            result = _get_backend().run_script(STATE_SCRIPT)
            parsed = json.loads(result)
            if not isinstance(parsed, dict) or not isinstance(parsed.get("version"), str) or not isinstance(parsed.get("documents"), list):
                raise RuntimeError("invalid_state_response: Illustrator snapshot could not be verified")
            return result
        result = await safety.execute(read_state, read_only=True, recover=recover)
        return [types.TextContent(type="text", text=result)]
    if name == "view":
        return await safety.execute(capture_illustrator, read_only=True)
    
    elif name == "run":
        if not arguments or "code" not in arguments:
            raise ValueError("invalid_argument: code is required")
        wrapped = wrap(arguments["code"], arguments.get("target_path"))
        result = await safety.execute(lambda: _get_backend().run_script(wrapped), timeout=arguments.get("timeout_seconds", 30))
        return [types.TextContent(type="text", text=result)]
    
    elif name == "get_prompt_suggestions":
        try:
            suggestions = get_prompt_suggestions()
            category = arguments.get("category") if arguments else None
            
            if category:
                # Filter by category
                category_map = {
                    "basic_shapes": "🎨 Basic Shapes & Geometry",
                    "typography": "📝 Typography & Text", 
                    "logos": "🏢 Logos & Branding",
                    "illustrations": "🌆 Illustrations & Scenes",
                    "icons": "🎭 Icons & UI Elements",
                    "artistic": "🎨 Artistic & Creative",
                    "charts": "📊 Charts & Infographics",
                    "print": "🏷️ Print & Layout"
                }
                
                full_category = category_map.get(category)
                if full_category and full_category in suggestions:
                    filtered_suggestions = {full_category: suggestions[full_category]}
                    result_text = f"**{full_category}**\n\n"
                    for suggestion in suggestions[full_category]:
                        result_text += f"• {suggestion}\n"
                else:
                    result_text = f"Category '{category}' not found. Available categories: {list(category_map.keys())}"
            else:
                # Return all suggestions
                result_text = "# 🎨 Illustrator Prompt Suggestions\n\n"
                for category, prompts in suggestions.items():
                    result_text += f"## {category}\n\n"
                    for prompt in prompts:
                        result_text += f"• {prompt}\n"
                    result_text += "\n"
            
            return [types.TextContent(type="text", text=result_text)]
        except Exception as e:
            logging.error(f"Error getting prompt suggestions: {str(e)}")
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]
    
    elif name == "get_system_prompt":
        try:
            system_prompt = get_system_prompt()
            return [types.TextContent(type="text", text=system_prompt)]
        except Exception as e:
            logging.error(f"Error getting system prompt: {str(e)}")
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]
    
    elif name == "get_prompting_tips":
        try:
            tips = get_prompting_tips()
            result_text = "# 💡 Prompting Tips for Adobe Illustrator\n\n"
            for tip in tips:
                result_text += f"{tip}\n"
            return [types.TextContent(type="text", text=result_text)]
        except Exception as e:
            logging.error(f"Error getting prompting tips: {str(e)}")
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]
    
    elif name == "get_advanced_template":
        try:
            template_type = arguments.get("template_type") if arguments else None
            parameters = arguments.get("parameters", {}) if arguments else {}
            
            if not template_type:
                return [types.TextContent(type="text", text="Template type is required")]
            
            templates = get_advanced_templates()
            if template_type in templates:
                if parameters:
                    # Try to format with parameters
                    try:
                        formatted_template = format_advanced_template(template_type, **parameters)
                        return [types.TextContent(type="text", text=formatted_template)]
                    except KeyError as e:
                        # Missing parameters, return template with placeholders
                        template = templates[template_type]
                        result_text = f"**{template_type.replace('_', ' ').title()} Template:**\n\n{template}\n\n"
                        result_text += f"**Missing parameter:** {str(e)}\n"
                        result_text += "Please provide the required parameters to fill in the template."
                        return [types.TextContent(type="text", text=result_text)]
                else:
                    # Return template with placeholders
                    template = templates[template_type]
                    result_text = f"**{template_type.replace('_', ' ').title()} Template:**\n\n{template}"
                    return [types.TextContent(type="text", text=result_text)]
            else:
                available_templates = list(templates.keys())
                return [types.TextContent(type="text", text=f"Template '{template_type}' not found. Available templates: {available_templates}")]
        except Exception as e:
            logging.error(f"Error getting advanced template: {str(e)}")
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]
    
    elif name == "help":
        try:
            help_text = display_help()
            return [types.TextContent(type="text", text=help_text)]
        except Exception as e:
            logging.error(f"Error displaying help: {str(e)}")
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]
    
    else:
        error_msg = f"Unknown tool: {name}"
        logging.error(error_msg)
        raise ValueError(error_msg)

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None):
    try:
        content = await _handle_call_tool(name, arguments)
        failed = name != "run" and any(isinstance(c, types.TextContent) and c.text.startswith(("Failed to", "Error:", "No code provided", "Template type is required")) for c in content)
        return types.CallToolResult(content=content, isError=failed)
    except Exception as error:
        message = str(error)
        code = next((x for x in ("outcome_unknown", "queue_timeout", "invalid_argument", "document_not_found", "ambiguous_document") if x in message), "execution_failed")
        return types.CallToolResult(isError=True, content=[types.TextContent(type="text", text=json.dumps({"ok":False,"code":code,"message":message,"suggested_next_tool":"get_state"}, ensure_ascii=False))])

async def main():
    try:
        print("Initializing MCP server for Illustrator...", file=sys.stderr)
        sys.stderr.flush()
        logging.info("Initializing MCP server for Illustrator.")
        
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            print("Server streams established, starting server...", file=sys.stderr)
            sys.stderr.flush()
            _print_client_config_hint()
            
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="illustrator",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
            print("Server finished running", file=sys.stderr)
            sys.stderr.flush()
    except Exception as e:
        print(f"Error in main: {e}", file=sys.stderr)
        sys.stderr.flush()
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        raise

if __name__ == "__main__":
    try:
        print("Starting the main event loop...", file=sys.stderr)
        logging.info("Starting the main event loop.")
        asyncio.run(main())
    except Exception as e:
        print(f"Error starting server: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
