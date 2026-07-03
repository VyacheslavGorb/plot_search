import urllib.request
import json

def get_routed_distance(origin_lat, origin_lon, dest_lat, dest_lon):
    query = f"""
    {{
      plan(
        from: {{lat: {origin_lat}, lon: {origin_lon}}}
        to: {{lat: {dest_lat}, lon: {dest_lon}}}
        transportModes: [{{mode: CAR}}]
      ) {{
        itineraries {{
          legs {{
            distance
          }}
        }}
      }}
    }}
    """
    req = urllib.request.Request("http://localhost:8080/otp/routers/default/index/graphql", data=json.dumps({'query': query}).encode('utf-8'))
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        print(data)
        
get_routed_distance(52.2275, 21.0003, 52.2285, 20.9840)
