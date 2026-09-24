import os, sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
import enhanced_visualizations as ev
if __name__ == "__main__": ev.p2_viz("p2-2", "p2-2")
