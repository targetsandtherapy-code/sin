"""合并 dealer_models 到 init_data.json"""
import json

with open("init_data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

with open("dealer_models.json", "r", encoding="utf-8") as f:
    dm = json.load(f)

# 去重
for erp in dm:
    dm[erp] = list(dict.fromkeys(dm[erp]))

data["dealer_models"] = dm

with open("init_data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"经销商-车型关系: {len(dm)} 条")
sample = list(dm.items())[:3]
for erp, codes in sample:
    print(f"  {erp}: {codes}")
