import os, sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
import enhanced_visualizations as ev
if __name__ == "__main__": ev.p3_viz("p3-1", "p3-1")
