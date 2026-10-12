"""Decode Valhalla encoded polyline6; retain actual routed street geometry.

This is graph traversal geometry, not a curb-verified bus swept path.
"""
import math

def decode_polyline6(encoded):
    if not isinstance(encoded,str) or not encoded:
        raise ValueError("Missing encoded Valhalla shape")
    coords=[]
    lat=lon=0
    i=0
    while i<len(encoded):
        values=[]
        for axis in range(2):
            shift=0
            value=0
            while True:
                if i>=len(encoded):raise ValueError("Truncated shape")
                code=ord(encoded[i])-63
                i+=1
                if code<0 or code>63:raise ValueError("Invalid encoded shape character")
                value|=(code&31)<<shift
                shift+=5
                if shift>40:raise ValueError("Polyline overflow")
                if not code&32:break
            values.append(-(value>>1)-1 if value&1 else value>>1)
        lat+=values[0]
        lon+=values[1]
        x,y=lon/1000000,lat/1000000
        if not (math.isfinite(x) and math.isfinite(y) and -180<=x<=180 and -90<=y<=90):
            raise ValueError("Polyline coordinates out of range")
        coords.append([x,y])
    if len(coords)<2:raise ValueError("Polyline too short")
    return coords

def extract_shape(route):
    trip=route.get("trip",{})
    legs=trip.get("legs") or []
    if not legs:
        return {"status":"NO_SHAPE_IN_BACKEND_RESPONSE","geometry":None,
                "method":"Valhalla trip.legs[].shape encoded polyline6"}
    combined=[]
    for leg in legs:
        shape=leg.get("shape")
        if not shape:
            return {"status":"NO_SHAPE_IN_BACKEND_RESPONSE","geometry":None,
                    "method":"Valhalla trip.legs[].shape encoded polyline6"}
        pts=decode_polyline6(shape)
        if combined and combined[-1]==pts[0]:pts=pts[1:]
        combined.extend(pts)
    return {"status":"ROAD_GRAPH_SHAPE_NOT_SWEPT_PATH",
            "geometry":{"type":"LineString","coordinates":combined},
            "vertex_count":len(combined),
            "method":"Valhalla trip.legs[].shape encoded polyline6",
            "turn_approved":False}

def encode_test_polyline6(coords):
    prev=[0,0]
    parts=[]
    for lon,lat in coords:
        pair=[round(lat*1e6),round(lon*1e6)]
        for idx,num in enumerate(pair):
            delta=num-prev[idx]
            prev[idx]=num
            shifted=delta<<1 if delta>=0 else ((-delta)<<1)-1
            while shifted>=32:
                parts.append(chr((32 | (shifted&31))+63))
                shifted>>=5
            parts.append(chr(shifted+63))
    return "".join(parts)
