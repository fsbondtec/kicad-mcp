

import sys
import json
from pathlib import Path
import logging
import os

# Project Path Setup
project_root = Path("C:/GIT/kicad-mcp/kicad_mcp/utils")
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root.parent))  # Add parent directory too

logging.basicConfig(filename="C:/Git/kicad-mcp/mcp_sunprocess.log", level=logging.DEBUG)


try:
    import pcbnew
    KICAD_AVAILABLE = True
except ImportError:
    KICAD_AVAILABLE = False


# Import separate utils
try:
    from utils.set_components_utils import ComponentManager
    from utils.board_utils import BoardManager
    UTILS_AVAILABLE = True
except ImportError as e:
    print(json.dumps({{"success": False, "error": f"Utils import failed: {{str(e)}}"}}, indent=2))
    UTILS_AVAILABLE = False

# Global instances
if UTILS_AVAILABLE:
    board_manager = BoardManager()
    component_manager = ComponentManager()

if __name__ == "__main__":
    try:
        if not UTILS_AVAILABLE:
            print(json.dumps({{"success": False, "error": "Utils not available"}}))
            sys.exit(1)
            
        method_name = sys.argv[1]
        params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {{}}
        
        if method_name == "load_board":
            result = board_manager.load_board(params["project_path"])
            if result["success"]:
                component_manager.set_board(board_manager.get_board())
                logging.debug(json.dumps(result))

            print(json.dumps(result))
           
        
        elif method_name == "place_component_full":
            project_path = params["project_path"]
            
            # Step 1: Load board
            logging.debug("DEBUG: Loading board...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")
            
            # Step 2: Place component
            logging.debug("DEBUG: Placing component...")
            footprint = component_manager.create_footprint(
                component_id=params["component_id"],
                position=params["position"],
                library=params["library"],
                reference=params.get("reference"),
                value=params.get("value"),
                rotation=params.get("rotation", 0),
                layer=params.get("layer", "F.Cu"),
            )
            component_info = component_manager.place_footprint(footprint)
            logging.debug("DEBUG: Component placed successfully")
            
            # Step 3: Save board
            logging.debug("DEBUG: Saving board...")
            save_result = board_manager.save_board(params.get("output_path"))
            if not save_result["success"]:
                print(json.dumps(save_result))
                sys.exit(1)
            
            logging.debug("DEBUG: Board saved successfully")
            
            result = {{
                "success": True,
                "message": f"Component placed and saved: {{params['component_id']}}",
                "component": {{
                    "reference": component_info.reference,
                    "value": component_info.value,
                    "footprint": component_info.footprint,
                    "position": component_info.position,
                    "rotation": component_info.rotation,
                    "layer": component_info.layer,
                }},
                "board_info": load_result.get("board_info", {{}}),
                "save_info": save_result
            }}
            logging.debug(json.dumps(result))
            print(json.dumps(result))

        elif method_name == "move_component":
            project_path = params["project_path"]
            reference = params.get("reference")
            position = params["position"]
            rotation = params.get("rotation")
            
            # Step 1: Load board
            logging.debug("DEBUG: Loading board for move operation...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")
            
            # Step 2: Move component
            logging.debug("DEBUG: Moving component ...")
            try:
                move_result = component_manager.move_component(
                    reference=reference,
                    position=position,
                    rotation=rotation
                )
                
                logging.debug(move_result.reference)    
                logging.debug("DEBUG: Component moved successfully")
                
                # Step 3: Save board
                logging.debug("DEBUG: Saving board...")
                save_result = board_manager.save_board()
                if not save_result["success"]:
                    print(json.dumps(save_result))
                    sys.exit(1)
                
                logging.debug("DEBUG: Board saved successfully")
                
                # Return combined result
                result = {{
                    "success": True,
                    "message": "Component moved successfully",
                    "component": {{
                        "reference": reference,
                        "position": position,
                        "rotation": rotation
                    }},
                    "board_info": load_result.get("board_info", {{}}),
                    "save_info": save_result
                }}
                logging.debug(json.dumps(result))
                print(json.dumps(result))
                
            except Exception as e:
                error_result = {{
                    "success": False,
                    "error": f"Failed to move component: {{str(e)}}"
                }}
                logging.error(json.dumps(error_result))
                print(json.dumps(error_result))

        elif method_name == "get_net_pcb":
            project_path = params["project_path"]

            logging.debug("DEBUG: Loading board...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")

            logging.debug("DEBUG: Extracting Nets ...")
            
            try:
                net_extract = board_manager.get_net_list()
                
                if net_extract["success"]:
                    logging.debug("DEBUG: Nets extracted successfully")
                    print(json.dumps(net_extract))
                else:
                    print(json.dumps(net_extract))
                    sys.exit(1)
                    
            except Exception as e:
                error_result = {
                    "success": False,
                    "message": "Exception occurred during net extraction",
                    "error": str(e)
                }
                logging.error(f"ERROR: Exception during net extraction: {str(e)}")
                print(json.dumps(error_result))
                sys.exit(1)

        elif method_name == "track_pcb_routes":
            project_path = params["project_path"]
        
            logging.debug("DEBUG: Loading board...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")

            #Set track 
            all_results = [] 
            try:
                routes = params["route"]

                for route in routes:
                    start = route.get("start")
                    end = route.get("end")
                    layer = route.get("layer")
                    width = route.get("width")
                    net = route.get("net")

                    # Validate the route parameters
                    if not all([start, end, layer, width, net]):
                        error_result = {
                            "success": False,
                            "message": "Missing required route parameters",
                            "route": route
                        }
                        logging.error(f"ERROR: Missing required parameters for route: {route}")
                        all_results.append(error_result)
                        continue

                    # Trace track for this route
                    trace_track = board_manager.trace_routes(start=start, end=end, layer=layer, width=width, net=net)

                    if not trace_track["success"]:
                        logging.error(f"ERROR: Failed to route: {trace_track.get('message', 'Unknown error')}")
                        all_results.append(trace_track)
                        continue

                    all_results.append(trace_track)


                # Step 3: Save board
                logging.debug("DEBUG: Saving board...")
                save_result = board_manager.save_board()
                
                if not save_result["success"]:
                    print(json.dumps(save_result))
                    sys.exit(1)

                logging.debug("DEBUG: Board saved successfully")

                result = {
                    "success": True,
                    "message": "Routing operation completed",
                    "routes": all_results,  # Include the results for each route
                    "save_info": save_result
                }

                logging.debug(json.dumps(result))
                print(json.dumps(result))

            except Exception as e:
                error_result = {
                    "success": False,
                    "message": "Exception occurred during routing",
                    "error": str(e)
                }
                logging.error(f"ERROR: Exception during routing: {str(e)}")
                all_results.append(error_result)
                logging.debug(json.dumps(result))
                print(json.dumps(result))

        elif method_name == "extract_basic_info":
            project_path = params["project_path"]
        
            logging.debug("DEBUG: Loading board for...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")

            try:
                pcb_info = board_manager.basic_board_info()
                
                if pcb_info["success"]:
                    logging.debug("DEBUG: Info extracted successfully")
                    print(json.dumps(pcb_info))
                else:
                    print(json.dumps(pcb_info))
                    sys.exit(1)

            except Exception as e:
                error_result = {
                    "success": False,
                    "message": "Exception occurred during info extraction",
                    "error": str(e)
                }
                logging.error(f"ERROR: Exception during info extraction: {str(e)}")
                print(json.dumps(error_result))
                sys.exit(1)

        elif method_name == "extract_designRules":
            project_path = params["project_path"]
        
            #load current board
            logging.debug("DEBUG: Loading board for...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")

            try:
                pcb_info = board_manager.get_design_rules()
                
                if pcb_info["success"]:
                    logging.debug("DEBUG: Info extracted successfully")
                    print(json.dumps(pcb_info))
                else:
                    print(json.dumps(pcb_info))
                    sys.exit(1)

            except Exception as e:
                error_result = {
                    "success": False,
                    "message": "Exception occurred during info extraction",
                    "error": str(e)
                }
                logging.error(f"ERROR: Exception during info extraction: {str(e)}")
                print(json.dumps(error_result))
                sys.exit(1)

        elif method_name == "extract_layers":
            project_path = params["project_path"]
        
            #load current board
            logging.debug("DEBUG: Loading board for...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")

            try:
                pcb_info = board_manager.get_layers()
                
                if pcb_info["success"]:
                    logging.debug("DEBUG: Info extracted successfully")
                    print(json.dumps(pcb_info))
                else:
                    print(json.dumps(pcb_info))
                    sys.exit(1)

            except Exception as e:
                error_result = {
                    "success": False,
                    "message": "Exception occurred during info extraction",
                    "error": str(e)
                }
                logging.error(f"ERROR: Exception during info extraction: {str(e)}")
                print(json.dumps(error_result))
                sys.exit(1)

        elif method_name == "extract_pads":
            project_path = params["project_path"]
        
            #load current board
            logging.debug("DEBUG: Loading board for...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")

            try:
                pcb_info = board_manager.get_footprints_pads()
                
                if pcb_info["success"]:
                    logging.debug("DEBUG: Info extracted successfully")
                    print(json.dumps(pcb_info))
                else:
                    print(json.dumps(pcb_info))
                    sys.exit(1)

            except Exception as e:
                error_result = {
                    "success": False,
                    "message": "Exception occurred during info extraction",
                    "error": str(e)
                }
                logging.error(f"ERROR: Exception during info extraction: {str(e)}")
                print(json.dumps(error_result))
                sys.exit(1)


        elif method_name == "extract_track_vias":
            project_path = params["project_path"]
        
            logging.debug("DEBUG: Loading board for...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")

            try:
                pcb_info = board_manager.get_tracks_vias()
                
                if pcb_info["success"]:
                    logging.debug("DEBUG: Info extracted successfully")
                    print(json.dumps(pcb_info))
                else:
                    print(json.dumps(pcb_info))
                    sys.exit(1)

            except Exception as e:
                error_result = {
                    "success": False,
                    "message": "Exception occurred during info extraction",
                    "error": str(e)
                }
                logging.error(f"ERROR: Exception during info extraction: {str(e)}")
                print(json.dumps(error_result))
                sys.exit(1)

        elif method_name == "extract_zones":
            project_path = params["project_path"]
        
            #load current board
            logging.debug("DEBUG: Loading board for...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")

            try:
                pcb_info = board_manager.get_zones()
                
                if pcb_info["success"]:
                    logging.debug("DEBUG: Info extracted successfully")
                    print(json.dumps(pcb_info))
                else:
                    print(json.dumps(pcb_info))
                    sys.exit(1)

            except Exception as e:
                error_result = {
                    "success": False,
                    "message": "Exception occurred during info extraction",
                    "error": str(e)
                }
                logging.error(f"ERROR: Exception during info extraction: {str(e)}")
                print(json.dumps(error_result))
                sys.exit(1)


        elif method_name == "extract_basic_info":
            project_path = params["project_path"]
        
            #load current board
            logging.debug("DEBUG: Loading board for...")
            load_result = board_manager.load_board(project_path)
            if not load_result["success"]:
                print(json.dumps(load_result))
                sys.exit(1)
            
            # Set board in component manager
            component_manager.set_board(board_manager.get_board())
            logging.debug("DEBUG: Board loaded successfully")

            try:
                pcb_info = board_manager.basic_board_info()
                
                if pcb_info["success"]:
                    logging.debug("DEBUG: Info extracted successfully")
                    print(json.dumps(pcb_info))
                else:
                    print(json.dumps(pcb_info))
                    sys.exit(1)

            except Exception as e:
                error_result = {
                    "success": False,
                    "message": "Exception occurred during info extraction",
                    "error": str(e)
                }
                logging.error(f"ERROR: Exception during info extraction: {str(e)}")
                print(json.dumps(error_result))
                sys.exit(1)
        
        else:
            print(json.dumps({{"success": False, "error": f"Unknown method: {{method_name}}"}}))
            
    except Exception as e:
        print(json.dumps({{"success": False, "error": str(e)}}))


    
