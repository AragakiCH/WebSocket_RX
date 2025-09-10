from opcua import Client
URL = "opc.tcp://192.168.18.68:4840"  # cámbialo si toca
print("Connecting to", URL)
c = Client(URL, timeout=8.0)
c.connect_and_get_server_endpoints()
print("✅ Endpoints OK")
