import os
import sys

# Add parent directory to path so we can import graph
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "sk-dummy-key-for-graph-visualization")

from graph import workflow

def generate_graph_image():
    print("Compiling workflow graph...")
    # We compile without checkpointer just to get the static graph visualization
    compiled_app = workflow.compile()
    
    graph_obj = compiled_app.get_graph()
    
    # 1. Save Mermaid text representation
    mermaid_text = graph_obj.draw_mermaid()
    mermaid_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflow_graph.mermaid")
    with open(mermaid_path, "w", encoding="utf-8") as f:
        f.write(mermaid_text)
    print(f"Saved Mermaid diagram syntax to: {mermaid_path}")
    
    # 2. Try to save PNG image using draw_mermaid_png()
    png_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflow_graph.png")
    try:
        png_data = graph_obj.draw_mermaid_png()
        with open(png_path, "wb") as f:
            f.write(png_data)
        print(f"Successfully generated and saved graph image to: {png_path}")
    except Exception as e:
        print(f"Could not generate PNG automatically (perhaps network/mermaid-ink issue): {e}")
        print("You can copy the contents of workflow_graph.mermaid into https://mermaid.live to view or export the image!")

if __name__ == "__main__":
    generate_graph_image()
