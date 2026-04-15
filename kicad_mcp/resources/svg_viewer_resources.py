"""
SVG viewer resource – renders an HTML app that displays SVG files
served by the local file server started in graph_tools.
"""

from fastmcp import FastMCP
from fastmcp.server.apps import AppConfig, ResourceCSP

from kicad_mcp.utils.svg_file_server import IMAGE_VIEW_URI, FILE_SERVER_PORT


def register_svg_viewer_resources(mcp: FastMCP) -> None:
    """Register the SVG viewer HTML resource with the MCP server."""

    @mcp.resource(
        IMAGE_VIEW_URI,
        app=AppConfig(
            csp=ResourceCSP(
                resource_domains=[
                    "https://unpkg.com",
                    f"http://localhost:{FILE_SERVER_PORT}",
                ],
                frame_domains=["*"],
            )
        ),
    )
    def svg_viewer_app() -> str:
        """Interactive SVG viewer for KiCad schematic path highlights."""
        return f"""\
<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: sans-serif; margin: 0; background: transparent; color: #333; }}

  #toolbar {{
    display: none;
    align-items: center;
    gap: 8px;
    position: sticky; top: 0;
    background: rgba(255,255,255,.95);
    border-bottom: 1px solid #ccc;
    z-index: 10;
    padding: 6px 12px;
    font-size: 12px; font-family: monospace;
  }}

  #toolbar button {{
    font-size: 11px; padding: 2px 8px; cursor: pointer;
    border: 1px solid #aaa; border-radius: 3px; background: #f5f5f5;
  }}
  #toolbar button:disabled {{ opacity: 0.4; cursor: default; }}
  #page-info {{ color: #888; font-size: 11px; margin-left: auto; }}

  #container {{ width: 100%; overflow: auto; border-radius: 0 0 8px 8px; box-shadow: 0 4px 12px rgba(0,0,0,.3); }}

  #svg-wrap {{ width: 100%; transform-origin: top left; cursor: zoom-in; min-height: 400px; }}
  #svg-wrap.zoomed {{ cursor: zoom-out; }}
  #svg-wrap img {{ width: 100%; height: auto; display: block; }}
  #loader {{ padding: 20px; color: #888; }}
  #error  {{ color: tomato; padding: 10px; font-weight: bold; }}

  @media (prefers-color-scheme: dark) {{
    body {{ background: #000000; color: #eeeeee; }}
    #toolbar {{ background: rgba(20, 20, 20, 0.95); border-bottom: 1px solid #444; }}
    #toolbar button {{ background: #333333; border: 1px solid #555; color: #eeeeee; }}
    #container {{ background: #000000; box-shadow: 0 4px 12px rgba(255,255,255,.1); }}
    #svg-wrap svg, #svg-wrap img {{ filter: invert(1) hue-rotate(180deg); }}
  }}
</style>
</head>
<body>
<div id="toolbar">
  <button id="btn-prev" disabled>&#9664; Prev</button>
  <span id="page-title" style="font-weight:bold"></span>
  <button id="btn-next" disabled>Next &#9654;</button>
  <span id="page-info"></span>
</div>
<div id="container">
  <div id="loader">Warte auf SVG…</div>
  <div id="svg-wrap"></div>
</div>

<script type="module">
import {{ App }} from "https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps";

const app = new App({{ name: "KiCad SVG Viewer", version: "1.0.0" }});

let urls = [], names = [], current = 0, zoomed = false;

const toolbar  = document.getElementById("toolbar");
const wrap     = document.getElementById("svg-wrap");
const btnPrev  = document.getElementById("btn-prev");
const btnNext  = document.getElementById("btn-next");
const pageInfo = document.getElementById("page-info");
const pageTit  = document.getElementById("page-title");

function showPage(index) {{
  current = index; zoomed = false;
  wrap.classList.remove("zoomed");
  wrap.style.width = "100%";
  wrap.innerHTML = "";

  const img = document.createElement("img");
  img.alt = names[index] ?? "";
  img.onerror = () => {{
    wrap.innerHTML = `<div id="error">Bild konnte nicht geladen werden:<br><code>${{urls[index]}}</code></div>`;
  }};
  img.onload = () => wrap.addEventListener("click", onWrapClick);
  img.src = urls[index];
  wrap.appendChild(img);

  pageTit.textContent = names[index] ?? `Sheet ${{index + 1}}`;
  pageInfo.textContent = `(${{index + 1}} / ${{urls.length}})`;
  btnPrev.disabled = index === 0;
  btnNext.disabled = index === urls.length - 1;
}}

function onWrapClick(e) {{
  zoomed = !zoomed;
  const container = document.getElementById("container");
  const cr = container.getBoundingClientRect();
  const mx = e.clientX - cr.left, my = e.clientY - cr.top;

  if (zoomed) {{
    const rb = wrap.getBoundingClientRect();
    const nx = (container.scrollLeft + mx) / rb.width;
    const ny = (container.scrollTop  + my) / rb.height;
    wrap.classList.add("zoomed");
    wrap.style.width = "300%";
    requestAnimationFrame(() => {{
      const ra = wrap.getBoundingClientRect();
      container.scrollTo({{ left: nx * ra.width - cr.width / 2, top: ny * ra.height - cr.height / 2, behavior: "instant" }});
    }});
  }} else {{
    wrap.classList.remove("zoomed");
    wrap.style.width = "100%";
    container.scrollTo({{ left: 0, top: 0, behavior: "instant" }});
  }}
}}

btnPrev.addEventListener("click", () => current > 0 && showPage(current - 1));
btnNext.addEventListener("click", () => current < urls.length - 1 && showPage(current + 1));

app.ontoolresult = ({{ content }}) => {{
  const text = content?.find(c => c.type === "text");
  if (!text) return;
  let data;
  try {{ data = JSON.parse(text.text); }} catch (e) {{ return; }}

  document.getElementById("loader")?.remove();

  if (data.error) {{
    wrap.innerHTML = `<div id="error">${{data.error}}</div>`;
    return;
  }}

  urls  = data.urls  ?? (data.url  ? [data.url]  : []);
  names = data.names ?? urls.map((_, i) => `Sheet ${{i + 1}}`);

  if (!urls.length) return;

  toolbar.style.display = "flex";
  btnPrev.style.display = urls.length > 1 ? "" : "none";
  btnNext.style.display = urls.length > 1 ? "" : "none";
  pageInfo.style.display = urls.length > 1 ? "" : "none";
  showPage(0);
}};

await app.connect();
</script>
</body>
</html>"""
