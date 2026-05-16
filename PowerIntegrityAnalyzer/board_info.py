import os
import pcbnew

class BoardBaselines():
    def __init__(self,board):
        self.board = board

    def _get_nets(self):
        """returns a dict of lists having key as net name and value as iterators"""
        nets = {}
        for t in self.board.GetTracks():
            w_mm = t.GetWidth() / 1e6
            length_mm = t.GetLength() / 1e6
            net = t.GetNetname()
            if net not in nets:
                nets[net] = []      
            # nets.setdefault(net, []).append(t)
            nets[net].append(t)  
        return nets
    
    def get_netInfo(self):
        """returns a dict having  avg width and total_length for a particular net
            netGraph[net]["avg_width"]
            netGraph[net]["total_length"]
        """
        nets = self._get_nets()
        netGraph = {}
        for net, tracks in nets.items():
            total_length = 0
            total_width = 0
            netGraph[net] = {}
            for t in tracks:
                total_length += t.GetLength()
                total_width += t.GetWidth()
            avg_width = (total_width / len(tracks)) / 1e6
            total_length_mm = total_length / 1e6
            netGraph[net]["avg_width"] = avg_width
            netGraph[net]["total_length"] = total_length_mm
        return netGraph
    
    def get_footPrints(self):
        """returns a Footmap of components R,L,C,U1, etc...
            ref_name : [ ( (x_mm,y_mm) ,net ) , ..... ]
        """
        footMaps = {}
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            footMaps[ref] = []
            for pad in fp.Pads():
                net = pad.GetNetname()
                pos = pad.GetPosition()
                x_mm = pos.x / 1e6
                y_mm = pos.y / 1e6
                if ref == "REF**":
                    continue
                footMaps[ref].append( ( (x_mm,y_mm) ,net )  )
        return footMaps