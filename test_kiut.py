import requests
import sys

def test_wms():
    # Coordinates of the test parcel from earlier: 
    # BBOX for POLYGON((685234.4 489577.8, ... , 684986.7 489137.5, ...))
    # Let's say BBOX is 684900,489100,685300,489600 (EPSG:2180)
    
    url = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzbrojeniaTerenu"
    params = {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.3.0",
        "LAYERS": "przewod_wodociagowy,przewod_kanalizacyjny,przewod_gazowy,przewod_elektroenergetyczny", 
        "STYLES": "",
        "CRS": "EPSG:2180",
        "BBOX": "489100,684900,489600,685300", # WMS 1.3.0 often flips X/Y depending on CRS, let's try standard 2180 Y,X or X,Y
        "WIDTH": "800",
        "HEIGHT": "800",
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE"
    }
    
    print("Testing KIUT WMS endpoint...")
    response = requests.get(url, params=params, verify=False)
    print(f"Status Code: {response.status_code}")
    print(f"Content Type: {response.headers.get('content-type')}")
    
    if response.status_code == 200 and 'image' in response.headers.get('content-type', ''):
        with open('test_kiut.png', 'wb') as f:
            f.write(response.content)
        print("Success! Image saved to test_kiut.png")
    else:
        print("Failed or returned XML. Here is a snippet:")
        print(response.text[:500])

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    test_wms()
