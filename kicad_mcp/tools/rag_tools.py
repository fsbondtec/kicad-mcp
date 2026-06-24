from pathlib import Path
from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from kicad_mcp.utils.search_rag import search


def register_rag_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def search_datasheets(query: str, k: int = 4) -> dict:
        """
        Search the indexed component datasheets for technical information.

        Use this tool whenever the user asks about:
        - Component specifications (voltage, current, frequency, temperature range)
        - Pin descriptions, pinouts or pin functions
        - Communication interfaces (I2C, SPI, UART, CAN, ...)
        - Register maps or configuration options
        - Electrical characteristics or absolute maximum ratings
        - Application circuits or recommended usage
        - Package dimensions or footprint details
        - anything slightly connected to a technical component

        Always list the pdf paths, where the information is from

        Args:
            query: Natural language description of what you are looking for.
                   Examples: "I2C address configuration", "output voltage range", "PWM frequency"
            k:     Number of results to return (default 4).

        Returns:
            A list of relevant datasheet excerpts with relevance scores.
            If a result contains a [Referenzbild: path] marker, call read_local_image
            with that path to visually inspect the diagram.
            Return die path to the pdf file where the information is from
            Returns an empty list if the RAG index is not yet ready.
        """
        results = search(query, top_k=k)

        if not results:
            return {
                "success": False,
                "message": "No results found. The index may still be initializing or no datasheets have been downloaded yet.",
                "results": [],
            }

        datasheets_referenced = sorted({r["source"] for r in results if r["source"]})

        return {
            "success": True,
            "datasheets_referenced": datasheets_referenced,
            "results": [
                {
                    "text": r["text"],
                    "score": round(r["score"], 3),
                    "source": r["source"],
                    "path": r["path"],
                    "section": r["section"],
                    "images": r["images"],
                }
                for r in results
            ],
        }

    @mcp.tool()
    async def read_local_image(image_path: str) -> Image:
        """
        Load a local image file and return it for visual analysis.

        Call this tool when a datasheet search result contains a
        [Referenzbild: /path/to/image.png] marker and you need to
        visually inspect the diagram, graph, pinout or table shown there.

        Args:
            image_path: Absolute path to the image file as shown in the
                        [Referenzbild: ...] marker.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        fmt = path.suffix.lstrip(".").lower()
        if fmt not in {"png", "jpg", "jpeg", "gif", "webp"}:
            fmt = "png"

        return Image(data=path.read_bytes(), format=fmt)
