from fastmcp import FastMCP
from kicad_mcp.utils.rag import search


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
        - anything slightly connected to a technichal component

        Args:
            query: Natural language description of what you are looking for.
                   Examples: "I2C address configuration", "output voltage range", "PWM frequency"
            k:     Number of results to return (default 4).

        Returns:
            A list of relevant datasheet excerpts with relevance scores.
            Returns an empty list if the RAG index is not yet ready (still initializing).
        """
        results = search(query, k=k)

        if not results:
            return {
                "success": False,
                "message": "No results found. The index may still be initializing or no datasheets have been downloaded yet.",
                "results": [],
            }

        return {
            "success": True,
            "results": [
                {"text": text, "score": round(score, 3)}
                for text, score in results
            ],
        }
