import os, sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,ROOT)
import enhanced_visualizations as ev
if __name__ == "__main__":
    ev.p1_viz("p1-1", os.path.join(os.path.dirname(__file__),"figures"), os.path.join(os.path.dirname(__file__),"outputs","p1-1_第1小问_基准组批.csv"))
