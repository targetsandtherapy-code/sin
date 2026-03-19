import requests, json

url = "https://sin-93r0.onrender.com/api/webhook/kuaishou"
data = {"clue_id": "test_log_check_001", "phone": "13800000001", "consumer_name": "测试记录"}
resp = requests.post(url, json=data)
print("Webhook:", resp.json())

url2 = "https://sin-93r0.onrender.com/login"
resp2 = requests.get(url2)
print("Login page:", resp2.status_code, "OK" if resp2.status_code == 200 else "FAIL")
