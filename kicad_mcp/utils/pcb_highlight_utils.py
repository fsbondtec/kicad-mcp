from typing import Dict, Any, Tuple

# new Kicad API instead of pcbnew:
from kipy import KiCad
from kipy.common_types import Vector2
from kipy.board_types import BoardSegment
from kipy.util import board_layer

class PcbHighlightManager:
    def __init__(self):
        self.highlight_cache = {}  # cache for all highlighted KIIDs

    def get_active_board(self) -> Tuple[Any, list]:
        errors = []
        try:
            kicad = KiCad()
            board = kicad.get_board()
            if not board:
                errors.append("No board is currently open in KiCad")
                return None, errors
            return board, errors
        except Exception as e:
            errors.append(f"Failed to connect to KiCad, get board: {str(e)}")
            return None, errors

    def mark_path(self, nets: list, layer: str) -> Dict[str, Any]:
            """
            Highlights the specified nets on the active KiCad board layout.

            This method connects to the currently open KiCad project, iterates through 
            the existing tracks, and creates highlight overlays for the specified nets. 
            The overlays are drawn as new board segments with double the width of the 
            original tracks on a specified layer.

            Args:
                nets (list): A list of net names (strings) to be highlighted.
                layer (str): The name of the layer to draw the highlights on 
                    (e.g., "Eco1.User"). If None, the method attempts to use "Eco1.User" 
                    or falls back to the first available user/eco layer.

            Returns:
                Dict[str, Any]: A dictionary containing the execution results 
            """

            result = {
                "success": False,
                "created_items_length": 0,
                "created_items": [],
                "highlighted_nets": [],
                "used_layer": None,
                "errors": [],
            }

            board, errors = self.get_active_board()
            if errors:
                result["errors"].extend(errors)
                return result

            if not nets:
                result["errors"].append("No nets provided")
                return result

            if not isinstance(nets, list):
                result["errors"].append("Nets must be a list")
                return result

            enabled_layer_names = []
            for l in board.get_enabled_layers():
                enabled_layer_names.append(board_layer.canonical_name(l))

            # choose given layer or Eco1 or user Layer
            if layer is not None:
                if layer in enabled_layer_names:
                    highlight_layer = board_layer.layer_from_canonical_name(layer)
                    result["used_layer"] = layer
                else:
                    result["errors"].append(
                        f"Layer '{layer}' not found. Available: {enabled_layer_names}"
                    )
                    return result
            else:
                default_layer = "Eco1.User"
                if default_layer in enabled_layer_names:
                    highlight_layer = board_layer.layer_from_canonical_name(default_layer)
                    result["used_layer"] = default_layer
                else:
                    user_layers = [l for l in enabled_layer_names if "Eco" in l or "User" in l]
                    if user_layers:
                        highlight_layer = board_layer.layer_from_canonical_name(user_layers[0])
                        result["used_layer"] = user_layers[0]
                    else:
                        result["errors"].append("No user layers available")
                        return result

            created_items = []
            created_items_id = []
            target_nets = nets

            if not target_nets:
                result["errors"].append("No valid net references found")
                return result

            # start the commit
            try:
                commit = board.begin_commit()
            except Exception as e:
                result["errors"].append(f"Failed to begin commit: {str(e)}")
                return result

            try:
                # Iterate through tracks
                tracks = board.get_tracks()
                if not tracks:
                    result["errors"].append("No tracks found on board")
                    board.push_commit(commit, "Highlighted Path - No tracks")
                    return result

                for track in board.get_tracks():
                    try:
                        net = track.net

                        if net and net.name in target_nets:
                            seg = BoardSegment()

                            start = Vector2()
                            start.x = track.start.x
                            start.y = track.start.y
                            seg.start = start

                            end = Vector2()
                            end.x = track.end.x
                            end.y = track.end.y
                            seg.end = end

                            # layer can be chosen
                            seg.layer = highlight_layer

                            # for highlight take double of original width
                            seg.attributes.stroke.width = int(track.width * 2)

                            created_item = board.create_items(seg)

                            if isinstance(created_item, list):
                                created_items.extend(created_item)
                                for item in created_items:
                                    created_items_id.append(item.id)

                            if net.name not in result["highlighted_nets"]:
                                result["highlighted_nets"].append(net.name)

                    except:
                        result["errors"].append(f"Failed to process track: {str(e)}")
                        continue

                if created_items:
                    try:
                        board.add_to_selection(created_items)
                        result["created_items_length"] = len(created_items)
                        result["created_items"] = created_items_id
                    except Exception as e:
                        result["errors"].append(f"Failed to add items to selection: {str(e)}")
                else:
                    result["errors"].append(f"No tracks found for given nets")

                try:
                    board.push_commit(commit, "Highlighted Path")
                    result["success"] = bool(created_items)
                except Exception as e:
                    result["errors"].append(f"Failed to push commit: {str(e)}")
                    return result

            except Exception as e:
                result["errors"].append(f"Error during track processing: {str(e)}")
                try:
                    board.push_commit(commit, "Highlighted Path - Failed")
                except:
                    pass
                return result


            return result

    def get_user_layers(self) -> Dict[str, Any]:
        board, errors = self.get_active_board()
        if errors:
            return {"available": ["Eco1.User"], "preferred_order": ["Eco1.User"], "error": errors[0]}

        if not board:
            return {"available": [], "preferred_order": [], "error": "No board open in KiCad"}

        enabled_layers = board.get_enabled_layers()
        layer_names = []

        for layer in enabled_layers:
            layer_names.append(board_layer.canonical_name(layer))

        user_layers = []
        for name in layer_names:
            if name.startswith("User") or name.startswith("Eco"):
                user_layers.append(name)

        # preferred order
        preferred = []
        for pref in ["Eco1.User", "Eco2.User"] + [f"User.{i}" for i in range(1, 10)]:
            if pref in user_layers:
                preferred.append(pref)

        for layer in user_layers:
            if layer not in preferred:
                preferred.append(layer)

        return {
            "available": user_layers,
            "preferred_order": preferred,
            "all_layers": layer_names,
        }

    


    def unmark_path(self, created_items: list) -> Dict[str, Any]:
            """
            unmarks the highlighted nets on the active KiCad board layout.

            Args:
                created_items (list): A list of net ids that need to be deleted

            Returns:
                Dict[str, Any]: A dictionary containing the execution results 
            """
            result = {"success": False, "deleted_items": 0, "errors": []}

            board, errors = self.get_active_board()
            if errors:
                result["errors"].extend(errors)
                return result
            
            try:
                commit = board.begin_commit()

                try:
                    board.remove_items_by_id(created_items)
                    result["deleted_items"] = len(created_items)
                except Exception as e:
                    result["errors"].append(f"Failed to delete items")

                board.push_commit(commit, "Removed Highlight Path")
                result["success"] = result["deleted_items"] > 0

            except Exception as e:
                result["errors"].append(f"Failed to clear highlights: {str(e)}")
                return result

            return result
