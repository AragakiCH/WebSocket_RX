from opcua import Client
import traceback

URL = "opc.tcp://192.168.17.60:4840"

c = Client(URL, timeout=5.0)

# Si tienes user/pass, descomenta:
c.set_user("boschrexroth")
c.set_password("boschrexroth")

try:
    c.connect()
    print("✅ CONNECT OK")

    eps = c.get_endpoints()
    print("Endpoints publicados:")
    for e in eps:
        print(" -", e.EndpointUrl, "|", e.SecurityPolicyUri, "|", e.SecurityMode)

except Exception as e:
    print("❌ ERROR:", repr(e))
    traceback.print_exc()

finally:
    try:
        c.disconnect()
    except:
        pass
