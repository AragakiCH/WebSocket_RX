from opcua import Client

url = "opc.tcp://192.168.17.60:4840"
c = Client(url, timeout=3)

c.connect()
eps = c.connect_and_get_server_endpoints()
c.disconnect()

for e in eps:
    print("Endpoint:", e.EndpointUrl)
    print("  SecurityPolicyUri:", e.SecurityPolicyUri)
    print("  SecurityMode:", e.SecurityMode)
    print("  UserTokens:", [p.TokenType.name for p in e.UserIdentityTokens])
    print("----")