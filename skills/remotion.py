"""Remotion Skill — programmatic video creation via Remotion CLI

Wraps the `npx remotion` CLI so agents can scaffold, preview,
and render React-based video compositions.

Usage: import REMOTION_TOOLS and execute_remotion_tool into any agent.
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_TIMEOUT = 300  # render can take a while

REMOTION_TOOLS = [
    {
        "name": "remotion_scaffold",
        "description": (
            "Create a new Remotion video project in the given directory. "
            "Uses a blank template and installs npm dependencies. "
            "Call this before any render or studio commands."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name of the project folder to create (kebab-case recommended).",
                },
                "dest_path": {
                    "type": "string",
                    "description": "Parent directory to create the project in. Defaults to current working directory.",
                    "default": ".",
                },
            },
            "required": ["project_name"],
        },
    },
    {
        "name": "remotion_render",
        "description": (
            "Render a Remotion composition to an mp4 video file. "
            "The project must already exist and have dependencies installed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Path to the Remotion project directory.",
                },
                "composition_id": {
                    "type": "string",
                    "description": "The composition ID registered in Root.tsx (e.g. 'MyComposition').",
                },
                "output": {
                    "type": "string",
                    "description": "Output file path. Defaults to 'out/video.mp4'.",
                    "default": "out/video.mp4",
                },
                "codec": {
                    "type": "string",
                    "description": "Output codec. Options: h264, h265, vp8, vp9, prores, gif. Default: h264.",
                    "default": "h264",
                },
                "scale": {
                    "type": "number",
                    "description": "Render scale multiplier (e.g. 2 for 2x resolution). Default: 1.",
                    "default": 1,
                },
            },
            "required": ["project_path", "composition_id"],
        },
    },
    {
        "name": "remotion_still",
        "description": (
            "Render a single frame from a Remotion composition as a PNG or JPEG image."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Path to the Remotion project directory.",
                },
                "composition_id": {
                    "type": "string",
                    "description": "The composition ID to render.",
                },
                "frame": {
                    "type": "integer",
                    "description": "Frame number to capture. Default: 0.",
                    "default": 0,
                },
                "output": {
                    "type": "string",
                    "description": "Output image path. Defaults to 'out/frame.png'.",
                    "default": "out/frame.png",
                },
            },
            "required": ["project_path", "composition_id"],
        },
    },
    {
        "name": "remotion_studio",
        "description": (
            "Start the Remotion Studio preview server for a project. "
            "Opens a browser-based scrubber and hot-reload preview. "
            "This is a long-running process — use only when the user explicitly wants to preview."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Path to the Remotion project directory.",
                },
            },
            "required": ["project_path"],
        },
    },
]


def execute_remotion_tool(name: str, inputs: dict) -> str:
    """Execute a Remotion CLI command and return its output."""

    if name == "remotion_scaffold":
        project_name = inputs.get("project_name", "").strip()
        dest_path    = inputs.get("dest_path", ".").strip() or "."
        if not project_name:
            return "[Error: project_name is required]"
        project_dir = os.path.join(dest_path, project_name)
        os.makedirs(project_dir, exist_ok=True)
        # Initialize with a blank package.json and install remotion
        pkg_json = (
            f'{{"name":"{project_name}","version":"1.0.0","scripts":{{'
            '"studio":"npx remotion studio","render":"npx remotion render"'
            '},"dependencies":{"remotion":"^4.0.0","react":"^18.0.0","react-dom":"^18.0.0"},'
            '"devDependencies":{"@remotion/cli":"^4.0.0","typescript":"^5.0.0"}}}'
        )
        pkg_path = os.path.join(project_dir, "package.json")
        with open(pkg_path, "w") as f:
            f.write(pkg_json)
        result = subprocess.run(
            ["npm", "install"],
            cwd=project_dir, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return f"[Scaffold error] npm install failed:\n{result.stderr}"
        return f"Remotion project '{project_name}' created at {os.path.abspath(project_dir)}.\nRun 'npx remotion studio' inside the folder to preview."

    elif name == "remotion_render":
        project_path   = inputs.get("project_path", "").strip()
        composition_id = inputs.get("composition_id", "").strip()
        output         = inputs.get("output", "out/video.mp4")
        codec          = inputs.get("codec", "h264")
        scale          = inputs.get("scale", 1)
        if not project_path or not composition_id:
            return "[Error: project_path and composition_id are required]"
        cmd = [
            "npx", "remotion", "render",
            composition_id, output,
            f"--codec={codec}",
            f"--scale={scale}",
        ]
        result = subprocess.run(
            cmd, cwd=project_path, capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            return f"[Render error]\n{result.stderr}"
        return f"Rendered '{composition_id}' → {output}\n{result.stdout.strip()}"

    elif name == "remotion_still":
        project_path   = inputs.get("project_path", "").strip()
        composition_id = inputs.get("composition_id", "").strip()
        frame          = inputs.get("frame", 0)
        output         = inputs.get("output", "out/frame.png")
        if not project_path or not composition_id:
            return "[Error: project_path and composition_id are required]"
        cmd = [
            "npx", "remotion", "still",
            composition_id,
            f"--frame={frame}",
            output,
        ]
        result = subprocess.run(
            cmd, cwd=project_path, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return f"[Still error]\n{result.stderr}"
        return f"Frame {frame} saved → {output}\n{result.stdout.strip()}"

    elif name == "remotion_studio":
        project_path = inputs.get("project_path", "").strip()
        if not project_path:
            return "[Error: project_path is required]"
        return (
            f"To start Remotion Studio, run this in a terminal:\n\n"
            f"  cd {project_path}\n"
            f"  npx remotion studio\n\n"
            "Studio runs as a long-lived server — it cannot be started inside an agent tool call."
        )

    return f"[Unknown remotion tool: {name}]"
