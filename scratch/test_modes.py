import urllib.request
import json

query = """
{
  plan(
    from: {lat: 52.170, lon: 20.810} # Pruszków
    to: {lat: 52.2275, lon: 21.0003} # Varso
    date: "2026-06-25"
    time: "08:00:00"
    transportModes: [{mode: CAR}, {mode: TRANSIT}, {mode: WALK}]
  ) { itineraries { duration } }
}
"""

req = urllib.request.Request("http://localhost:8080/otp/routers/default/index/graphql", data=json.dumps({'query': query}).encode())
req.add_header('Content-Type', 'application/json')
with urllib.request.urlopen(req) as resp:
    print("CAR+TRANSIT:", json.loads(resp.read()))

query = """
{
  plan(
    from: {lat: 52.170, lon: 20.810}
    to: {lat: 52.2275, lon: 21.0003}
    date: "2026-06-25"
    time: "08:00:00"
    transportModes: [{mode: BICYCLE}, {mode: TRANSIT}, {mode: WALK}]
  ) { itineraries { duration } }
}
"""

req = urllib.request.Request("http://localhost:8080/otp/routers/default/index/graphql", data=json.dumps({'query': query}).encode())
req.add_header('Content-Type', 'application/json')
with urllib.request.urlopen(req) as resp:
    print("BICYCLE+TRANSIT:", json.loads(resp.read()))
