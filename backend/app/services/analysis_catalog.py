from __future__ import annotations

from copy import deepcopy

CATEGORIES: list[dict] = [
    {"id": "general_building", "name": "建筑/构筑物类"},
    {"id": "infrastructure", "name": "公共基础设施类"},
    {"id": "electromagnetic", "name": "电磁环境保护类"},
    {"id": "cultural", "name": "文物保护类"},
]


def _threshold_params(micro: float | None, light: float | None, *, basis: str = "protection_zone") -> list[dict]:
    return [
        {"key": "micro_threshold_m", "label": "微型阈值(m)", "type": "number", "default": micro},
        {"key": "light_threshold_m", "label": "轻型阈值(m)", "type": "number", "default": light},
        {
            "key": "distance_basis",
            "label": "距离基准",
            "type": "enum",
            "default": basis,
            "options": ["centerline", "protection_zone"],
        },
        {"key": "query_timeout_s", "label": "查询超时(s)", "type": "number", "default": 25},
        {"key": "bbox_expand_m", "label": "查询范围扩展(m)", "type": "number", "default": 3000},
        {"key": "max_candidates", "label": "最大候选数", "type": "number", "default": 500},
    ]


def _manual_factor(*, factor_id: str, category_id: str, name: str, control_requirement: str, next_action: str) -> dict:
    return {
        "id": factor_id,
        "category_id": category_id,
        "name": name,
        "control_requirement": control_requirement,
        "capability": "manual_required",
        "parameter_schema": [],
        "default_params": {},
        "manual_schema": [
            {"key": "compliance", "label": "合规结论", "type": "enum", "options": ["pass", "fail", "unknown"]},
            {"key": "notes", "label": "说明", "type": "text"},
        ],
        "next_action_template": next_action,
    }


def _auto_query_factor(
    *,
    factor_id: str,
    category_id: str,
    name: str,
    control_requirement: str,
    micro: float | None,
    light: float | None,
    tag_filters: list[str],
    next_action: str,
    basis: str = "protection_zone",
    extra_params: list[dict] | None = None,
) -> dict:
    schema = _threshold_params(micro, light, basis=basis)
    if extra_params:
        schema.extend(extra_params)
    default_params = {item["key"]: item.get("default") for item in schema}
    return {
        "id": factor_id,
        "category_id": category_id,
        "name": name,
        "control_requirement": control_requirement,
        "capability": "auto_query",
        "query_engine": "overpass",
        "query_filters": tag_filters,
        "parameter_schema": schema,
        "default_params": default_params,
        "manual_schema": [
            {"key": "compliance", "label": "合规结论", "type": "enum", "options": ["pass", "fail", "unknown"]},
            {"key": "notes", "label": "说明", "type": "text"},
        ],
        "next_action_template": next_action,
    }


def _auto_db_factor(
    *,
    factor_id: str,
    category_id: str,
    name: str,
    control_requirement: str,
    micro: float | None,
    light: float | None,
    db_keywords: list[str],
    next_action: str,
    basis: str = "protection_zone",
) -> dict:
    schema = _threshold_params(micro, light, basis=basis)
    default_params = {item["key"]: item.get("default") for item in schema}
    return {
        "id": factor_id,
        "category_id": category_id,
        "name": name,
        "control_requirement": control_requirement,
        "capability": "auto_db",
        "db_keywords": db_keywords,
        "parameter_schema": schema,
        "default_params": default_params,
        "manual_schema": [
            {"key": "compliance", "label": "合规结论", "type": "enum", "options": ["pass", "fail", "unknown"]},
            {"key": "notes", "label": "说明", "type": "text"},
        ],
        "next_action_template": next_action,
    }


FACTORS: list[dict] = [
    _auto_query_factor(
        factor_id="general_building_structure",
        category_id="general_building",
        name="建筑/构筑物",
        control_requirement="建筑围界外50米（微型）/100米（轻型）范围内空域",
        micro=50,
        light=100,
        tag_filters=[
            'node["building"]',
            'way["building"]',
            'relation["building"]',
            'node["building:part"]',
            'way["building:part"]',
            'relation["building:part"]',
            'node["man_made"]',
            'way["man_made"]',
            'relation["man_made"]',
        ],
        next_action="补录建筑物边界后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_electrified_railway",
        category_id="infrastructure",
        name="铁路电气化线路",
        control_requirement="两侧100米（微型）/200米（轻型）范围内空域",
        micro=100,
        light=200,
        tag_filters=['way["railway"="rail"]', 'relation["railway"="rail"]'],
        next_action="补录铁路数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_elevated_urban_rail",
        category_id="infrastructure",
        name="城市轨道交通高架线路",
        control_requirement="两侧100米（微型）/200米（轻型）范围内空域",
        micro=100,
        light=200,
        tag_filters=['way["railway"~"subway|light_rail|tram"]', 'relation["railway"~"subway|light_rail|tram"]'],
        next_action="补录城市轨道数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_high_voltage_powerline",
        category_id="infrastructure",
        name="高压架空电力线路",
        control_requirement="两侧100米（微型）/200米（轻型）范围内空域",
        micro=100,
        light=200,
        tag_filters=['way["power"="line"]', 'relation["power"="line"]'],
        next_action="补录高压线路数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_power_plant",
        category_id="infrastructure",
        name="发电厂",
        control_requirement="厂站围界外50米（微型）/100米（轻型）范围内空域",
        micro=50,
        light=100,
        tag_filters=[
            'node["power"="plant"]',
            'way["power"="plant"]',
            'relation["power"="plant"]',
            'node["power"="plant"]["plant:source"~"coal|gas|oil|diesel|thermal|hydro|hydroelectric|nuclear|solar|wind|pumped_storage|biomass",i]',
            'way["power"="plant"]["plant:source"~"coal|gas|oil|diesel|thermal|hydro|hydroelectric|nuclear|solar|wind|pumped_storage|biomass",i]',
            'relation["power"="plant"]["plant:source"~"coal|gas|oil|diesel|thermal|hydro|hydroelectric|nuclear|solar|wind|pumped_storage|biomass",i]',
            'node["power"="plant"]["generator:source"~"coal|gas|oil|diesel|thermal|hydro|hydroelectric|nuclear|solar|wind|pumped_storage|biomass",i]',
            'way["power"="plant"]["generator:source"~"coal|gas|oil|diesel|thermal|hydro|hydroelectric|nuclear|solar|wind|pumped_storage|biomass",i]',
            'relation["power"="plant"]["generator:source"~"coal|gas|oil|diesel|thermal|hydro|hydroelectric|nuclear|solar|wind|pumped_storage|biomass",i]',
            'node["power"="plant"]["plant:method"~"pumped_storage",i]',
            'way["power"="plant"]["plant:method"~"pumped_storage",i]',
            'relation["power"="plant"]["plant:method"~"pumped_storage",i]',
            'node["power"="plant"]["name"~"火电|热电|水电|核电|光伏|风电|抽水蓄能|电厂|电站",i]',
            'way["power"="plant"]["name"~"火电|热电|水电|核电|光伏|风电|抽水蓄能|电厂|电站",i]',
            'relation["power"="plant"]["name"~"火电|热电|水电|核电|光伏|风电|抽水蓄能|电厂|电站",i]',
        ],
        next_action="补录发电厂（含火电/水电/核电/光伏/风电/抽蓄）数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_substation",
        category_id="infrastructure",
        name="变电站（换流站）",
        control_requirement="站址围界外50米（微型）/100米（轻型）范围内空域",
        micro=50,
        light=100,
        tag_filters=[
            'node["power"="converter"]',
            'way["power"="converter"]',
            'relation["power"="converter"]',
            'node["power"="substation"]',
            'way["power"="substation"]',
            'relation["power"="substation"]',
            'node["substation"]',
            'way["substation"]',
            'relation["substation"]',
            'node["name"~"变电站|换流站",i]',
            'way["name"~"变电站|换流站",i]',
            'relation["name"~"变电站|换流站",i]',
        ],
        next_action="补录变电站（换流站）数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_highway",
        category_id="infrastructure",
        name="高速公路",
        control_requirement="两侧100米（微型）/200米（轻型）范围内空域",
        micro=100,
        light=200,
        tag_filters=['way["highway"~"motorway|trunk|motorway_link"]', 'relation["highway"~"motorway|trunk|motorway_link"]'],
        next_action="补录高速公路数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_major_hydropower",
        category_id="infrastructure",
        name="重大水利水电设施",
        control_requirement="安全保卫区范围内空域",
        micro=100,
        light=200,
        tag_filters=['way["waterway"="dam"]', 'relation["waterway"="dam"]', 'way["water"="reservoir"]'],
        next_action="补录水利设施数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_fuel_station",
        category_id="infrastructure",
        name="加油（气）站",
        control_requirement="建筑围界附近空域",
        micro=30,
        light=50,
        tag_filters=['node["amenity"="fuel"]', 'way["amenity"="fuel"]', 'relation["amenity"="fuel"]'],
        next_action="补录加油（气）站数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_water_plant",
        category_id="infrastructure",
        name="供水厂",
        control_requirement="建筑围界外50米（微型）/100米（轻型）范围内空域",
        micro=50,
        light=100,
        tag_filters=[
            'node["man_made"="water_works"]',
            'way["man_made"="water_works"]',
            'relation["man_made"="water_works"]',
            'node["building"="water_tower"]',
            'way["building"="water_tower"]',
            'relation["building"="water_tower"]',
            'node["name"~"供水|水厂|净水厂|自来水",i]',
            'way["name"~"供水|水厂|净水厂|自来水",i]',
            'relation["name"~"供水|水厂|净水厂|自来水",i]',
        ],
        next_action="补录供水厂数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_transport_hub",
        category_id="infrastructure",
        name="公共交通枢纽",
        control_requirement="建筑围界外50米（微型）/100米（轻型）范围内空域",
        micro=50,
        light=100,
        tag_filters=[
            'node["railway"="station"]',
            'way["railway"="station"]',
            'relation["railway"="station"]',
            'node["railway"="halt"]',
            'way["railway"="halt"]',
            'relation["railway"="halt"]',
            'node["public_transport"="station"]',
            'way["public_transport"="station"]',
            'relation["public_transport"="station"]',
            'node["railway"="subway_entrance"]',
            'way["station"="subway"]',
            'relation["station"="subway"]',
            'node["public_transport"="stop_position"]["train"="yes"]',
            'node["public_transport"="platform"]["train"="yes"]',
            'node["amenity"="ferry_terminal"]',
            'way["amenity"="ferry_terminal"]',
            'relation["amenity"="ferry_terminal"]',
        ],
        next_action="若自动识别不足，请补录公共交通枢纽数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_aviation_electronics_hub",
        category_id="infrastructure",
        name="航电枢纽（水运发电站）",
        control_requirement="建筑围界外50米（微型）/100米（轻型）范围内空域",
        micro=50,
        light=100,
        tag_filters=[
            'node["power"="plant"]["plant:source"~"hydro|hydroelectric",i]',
            'way["power"="plant"]["plant:source"~"hydro|hydroelectric",i]',
            'relation["power"="plant"]["plant:source"~"hydro|hydroelectric",i]',
            'node["generator:source"~"hydro|hydroelectric",i]',
            'way["generator:source"~"hydro|hydroelectric",i]',
            'relation["generator:source"~"hydro|hydroelectric",i]',
            'way["waterway"~"dam|weir|lock_gate"]["power"]',
            'relation["waterway"~"dam|weir|lock_gate"]["power"]',
            'way["waterway"~"dam|weir|lock_gate"]["man_made"="hydro_power"]',
            'relation["waterway"~"dam|weir|lock_gate"]["man_made"="hydro_power"]',
        ],
        next_action="补录航电枢纽数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_port",
        category_id="infrastructure",
        name="港口",
        control_requirement="建筑围界外50米（微型）/100米（轻型）范围内空域",
        micro=50,
        light=100,
        tag_filters=['node["seamark:type"="harbour"]', 'way["landuse"="port"]', 'relation["landuse"="port"]'],
        next_action="补录港口数据后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_drinking_water_source",
        category_id="infrastructure",
        name="饮用水水源保护区",
        control_requirement="保护区范围内空域",
        micro=50,
        light=100,
        tag_filters=['relation["boundary"="protected_area"]', 'way["water"="reservoir"]'],
        next_action="补录饮用水水源保护区后重跑。",
    ),
    _auto_query_factor(
        factor_id="infra_other_public",
        category_id="infrastructure",
        name="其他公共基础设施",
        control_requirement="建筑围界外50米（微型）/100米（轻型）范围内空域",
        micro=50,
        light=100,
        tag_filters=['node["man_made"]', 'way["man_made"]', 'relation["man_made"]'],
        next_action="补录设施边界后重跑。",
    ),
    _auto_query_factor(
        factor_id="em_radio_astronomy",
        category_id="electromagnetic",
        name="射电天文台",
        control_requirement="3000米（微型）/5000米（轻型）范围内",
        micro=3000,
        light=5000,
        tag_filters=[
            'node["man_made"="observatory"]["observatory:type"~"astronomical|radio",i]',
            'way["man_made"="observatory"]["observatory:type"~"astronomical|radio",i]',
            'relation["man_made"="observatory"]["observatory:type"~"astronomical|radio",i]',
            'node["man_made"="telescope"]["telescope:type"="radio"]',
            'way["man_made"="telescope"]["telescope:type"="radio"]',
            'relation["man_made"="telescope"]["telescope:type"="radio"]',
            'node["name"~"射电天文|天文台|radio astronomy|radio telescope",i]',
            'way["name"~"射电天文|天文台|radio astronomy|radio telescope",i]',
            'relation["name"~"射电天文|天文台|radio astronomy|radio telescope",i]',
        ],
        next_action="导入权威天文台数据后复核。",
    ),
    _auto_query_factor(
        factor_id="em_satellite_control",
        category_id="electromagnetic",
        name="卫星测控（导航）站",
        control_requirement="1000米（微型）/2000米（轻型）范围内",
        micro=1000,
        light=2000,
        tag_filters=[
            'node["communication:space"~"ground_station|telemetry|ttc|control",i]',
            'way["communication:space"~"ground_station|telemetry|ttc|control",i]',
            'relation["communication:space"~"ground_station|telemetry|ttc|control",i]',
            'node["communication:satellite"="yes"]',
            'way["communication:satellite"="yes"]',
            'relation["communication:satellite"="yes"]',
            'node["man_made"="satellite_dish"]',
            'way["man_made"="satellite_dish"]',
            'relation["man_made"="satellite_dish"]',
            'node["monitoring:gps"="yes"]',
            'way["monitoring:gps"="yes"]',
            'relation["monitoring:gps"="yes"]',
            'node["name"~"卫星|测控|导航站|ground station|satellite",i]',
            'way["name"~"卫星|测控|导航站|ground station|satellite",i]',
            'relation["name"~"卫星|测控|导航站|ground station|satellite",i]',
        ],
        next_action="导入权威卫星站数据后复核。",
    ),
    _auto_query_factor(
        factor_id="em_air_nav_station",
        category_id="electromagnetic",
        name="航空无线电导航台",
        control_requirement="1000米（微型）/2000米（轻型）范围内",
        micro=1000,
        light=2000,
        tag_filters=[
            'node["beacon:type"~"VOR|DVOR|NDB|DME|TACAN|VORTAC",i]',
            'way["beacon:type"~"VOR|DVOR|NDB|DME|TACAN|VORTAC",i]',
            'relation["beacon:type"~"VOR|DVOR|NDB|DME|TACAN|VORTAC",i]',
            'node["aeroway"="navigationaid"]',
            'way["aeroway"="navigationaid"]',
            'relation["aeroway"="navigationaid"]',
            'node["airmark"="beacon"]',
            'way["airmark"="beacon"]',
            'relation["airmark"="beacon"]',
            'node["name"~"导航台|VOR|NDB|DME|TACAN|VORTAC",i]',
            'way["name"~"导航台|VOR|NDB|DME|TACAN|VORTAC",i]',
            'relation["name"~"导航台|VOR|NDB|DME|TACAN|VORTAC",i]',
        ],
        next_action="导入权威导航台数据后复核。",
    ),
    _auto_query_factor(
        factor_id="em_meteorological_radar",
        category_id="electromagnetic",
        name="气象雷达站",
        control_requirement="500米（微型）/1000米（轻型）范围内",
        micro=500,
        light=1000,
        tag_filters=[
            'node["weather:radar"="yes"]',
            'way["weather:radar"="yes"]',
            'relation["weather:radar"="yes"]',
            'node["tower:type"="radar"]',
            'way["tower:type"="radar"]',
            'relation["tower:type"="radar"]',
            'node["man_made"="tower"]["tower:type"="radar"]',
            'way["man_made"="tower"]["tower:type"="radar"]',
            'relation["man_made"="tower"]["tower:type"="radar"]',
            'node["man_made"="monitoring_station"]["monitoring:weather"="yes"]',
            'way["man_made"="monitoring_station"]["monitoring:weather"="yes"]',
            'relation["man_made"="monitoring_station"]["monitoring:weather"="yes"]',
            'node["name"~"气象雷达|weather radar|雷达站",i]',
            'way["name"~"气象雷达|weather radar|雷达站",i]',
            'relation["name"~"气象雷达|weather radar|雷达站",i]',
        ],
        next_action="导入权威雷达站数据后复核。",
    ),
    _auto_query_factor(
        factor_id="em_other_protected",
        category_id="electromagnetic",
        name="其他电磁保护设施",
        control_requirement="1000米（微型）/2000米（轻型）范围内",
        micro=1000,
        light=2000,
        tag_filters=[
            'node["tower:type"="communication"]',
            'way["tower:type"="communication"]',
            'relation["tower:type"="communication"]',
            'node["man_made"="communications_tower"]',
            'way["man_made"="communications_tower"]',
            'relation["man_made"="communications_tower"]',
            'node["man_made"="mast"]["communication:radio"="yes"]',
            'way["man_made"="mast"]["communication:radio"="yes"]',
            'relation["man_made"="mast"]["communication:radio"="yes"]',
            'node["communication:radio"="yes"]',
            'way["communication:radio"="yes"]',
            'relation["communication:radio"="yes"]',
            'node["name"~"通信|微波|发射台|电磁|基站|radio station",i]',
            'way["name"~"通信|微波|发射台|电磁|基站|radio station",i]',
            'relation["name"~"通信|微波|发射台|电磁|基站|radio station",i]',
        ],
        next_action="补录电磁保护设施后复核。",
    ),
    _auto_query_factor(
        factor_id="cultural_revolution_memorial",
        category_id="cultural",
        name="重要革命纪念地",
        control_requirement="按官方划定范围执行",
        micro=300,
        light=300,
        tag_filters=[
            'node["historic"~"memorial|monument",i]',
            'way["historic"~"memorial|monument",i]',
            'relation["historic"~"memorial|monument",i]',
            'node["memorial"]',
            'way["memorial"]',
            'relation["memorial"]',
            'node["name"~"革命纪念|革命旧址|烈士纪念|烈士陵园|纪念馆|纪念碑|纪念堂|纪念园",i]',
            'way["name"~"革命纪念|革命旧址|烈士纪念|烈士陵园|纪念馆|纪念碑|纪念堂|纪念园",i]',
            'relation["name"~"革命纪念|革命旧址|烈士纪念|烈士陵园|纪念馆|纪念碑|纪念堂|纪念园",i]',
        ],
        next_action="导入文保权威图层后复核。",
    ),
    _auto_query_factor(
        factor_id="cultural_immovable",
        category_id="cultural",
        name="重要不可移动文物",
        control_requirement="按官方划定范围执行",
        micro=300,
        light=300,
        tag_filters=[
            'node["heritage"]',
            'way["heritage"]',
            'relation["heritage"]',
            'node["protect_class"]',
            'way["protect_class"]',
            'relation["protect_class"]',
            'node["name"~"不可移动文物|文物保护单位|古建筑|古遗址|古墓葬|石窟寺|近现代重要史迹",i]',
            'way["name"~"不可移动文物|文物保护单位|古建筑|古遗址|古墓葬|石窟寺|近现代重要史迹",i]',
            'relation["name"~"不可移动文物|文物保护单位|古建筑|古遗址|古墓葬|石窟寺|近现代重要史迹",i]',
        ],
        next_action="导入文保权威图层后复核。",
    ),
]


_LINE_FACTOR_IDS = {
    "infra_electrified_railway",
    "infra_highway",
    "infra_elevated_urban_rail",
    "infra_high_voltage_powerline",
}

_AREA_FACTOR_IDS = {
    "infra_other_public",
    "em_radio_astronomy",
    "em_satellite_control",
    "em_air_nav_station",
    "em_meteorological_radar",
    "em_other_protected",
    "cultural_revolution_memorial",
    "cultural_immovable",
}

_THRESHOLD_OVERRIDES: dict[str, dict[str, float]] = {
    "general_building_structure": {"micro": 50, "light": 100},
    "infra_electrified_railway": {"micro": 100, "light": 200},
    "infra_elevated_urban_rail": {"micro": 100, "light": 200},
    "infra_high_voltage_powerline": {"micro": 100, "light": 200},
    "infra_power_plant": {"micro": 50, "light": 100},
    "infra_substation": {"micro": 50, "light": 100},
    "infra_highway": {"micro": 100, "light": 200},
    "infra_major_hydropower": {"micro": 100, "light": 200},
    "infra_fuel_station": {"micro": 30, "light": 50},
    "infra_water_plant": {"micro": 50, "light": 100},
    "infra_transport_hub": {"micro": 50, "light": 100},
    "infra_aviation_electronics_hub": {"micro": 50, "light": 100},
    "infra_port": {"micro": 50, "light": 100},
    "infra_drinking_water_source": {"micro": 50, "light": 100},
    "infra_other_public": {"micro": 50, "light": 100},
    "em_radio_astronomy": {"micro": 3000, "light": 5000},
    "em_satellite_control": {"micro": 1000, "light": 2000},
    "em_air_nav_station": {"micro": 1000, "light": 2000},
    "em_meteorological_radar": {"micro": 500, "light": 1000},
    "em_other_protected": {"micro": 1000, "light": 2000},
    "cultural_revolution_memorial": {"micro": 300, "light": 300},
    "cultural_immovable": {"micro": 300, "light": 300},
}


def _append_param_if_missing(factor: dict, param: dict) -> None:
    schema = factor.setdefault("parameter_schema", [])
    key = str(param.get("key") or "")
    if not key:
        return
    if any(str(item.get("key") or "") == key for item in schema):
        return
    schema.append(param)
    defaults = factor.setdefault("default_params", {})
    defaults[key] = param.get("default")


def _build_factor_metadata(factor: dict) -> dict:
    factor_id = str(factor.get("id") or "")
    category_id = str(factor.get("category_id") or "")
    capability = str(factor.get("capability") or "")

    if category_id == "cultural":
        data_source_mode = "import_primary_optional_auto" if capability == "auto_query" else "authoritative_import_required"
    elif category_id == "general_building":
        data_source_mode = "auto_query_with_authoritative" if capability == "auto_query" else "auto_db_with_authoritative"
    elif category_id == "electromagnetic":
        data_source_mode = "import_primary_optional_auto"
    elif category_id == "infrastructure":
        if factor_id == "infra_other_public":
            data_source_mode = "import_primary_auto_secondary"
        elif capability == "auto_db":
            data_source_mode = "auto_db_with_authoritative"
        elif capability == "auto_query":
            data_source_mode = "auto_query_with_authoritative"
        else:
            data_source_mode = "import_primary_auto_secondary"
    else:
        data_source_mode = "manual_required"

    if factor_id in _LINE_FACTOR_IDS:
        geometry_expectation = "line"
    elif factor_id in _AREA_FACTOR_IDS:
        geometry_expectation = "polygon"
    else:
        geometry_expectation = "point"

    defaults = factor.get("default_params") or {}
    default_thresholds = {
        "micro": defaults.get("micro_threshold_m"),
        "light": defaults.get("light_threshold_m"),
        "basis": defaults.get("distance_basis") or "protection_zone",
    }
    override = _THRESHOLD_OVERRIDES.get(factor_id)
    if override:
        default_thresholds["micro"] = override.get("micro")
        default_thresholds["light"] = override.get("light")
    if default_thresholds.get("micro") is None:
        default_thresholds["micro"] = 1000
    if default_thresholds.get("light") is None:
        default_thresholds["light"] = default_thresholds["micro"]

    return {
        "data_source_mode": data_source_mode,
        "geometry_expectation": geometry_expectation,
        "evaluation_rule": "intersects_or_min_distance_threshold" if geometry_expectation == "polygon" else "min_distance_threshold",
        "default_thresholds": default_thresholds,
        "evidence_schema": {
            "features": "GeoJSON feature list with distance",
            "metrics": {
                "nearest_distance_m": "float|null",
                "hit_count": "int",
                "threshold_m": "float|null",
                "basis": "string",
                "confidence": "low|medium|high",
                "source": "authoritative|auto_query|auto_db|manual",
            },
        },
    }


def _with_runtime_metadata(factor: dict) -> dict:
    item = deepcopy(factor)
    item.update(_build_factor_metadata(item))
    if str(item.get("category_id")) == "infrastructure":
        _append_param_if_missing(item, {"key": "query_range_m", "label": "提取范围(m)", "type": "number", "default": 500})
        _append_param_if_missing(item, {"key": "max_feature_count", "label": "最大要素数", "type": "number", "default": 100})
    if str(item.get("data_source_mode")) in {"authoritative_import_required", "import_primary_auto_secondary", "import_primary_optional_auto"}:
        _append_param_if_missing(item, {"key": "query_range_m", "label": "判定范围(m)", "type": "number", "default": 1000})
    return item


if len(FACTORS) != 22:
    raise RuntimeError(f"Expected 22 factors, got {len(FACTORS)}")


def get_catalog_payload() -> dict:
    category_map = {item["id"]: {"id": item["id"], "name": item["name"], "factors": []} for item in CATEGORIES}
    factors = [_with_runtime_metadata(item) for item in FACTORS]
    for factor in factors:
        category_map[factor["category_id"]]["factors"].append(factor["id"])
    categories = [category_map[item["id"]] for item in CATEGORIES]
    return {
        "version": "v1",
        "category_count": len(CATEGORIES),
        "factor_count": len(factors),
        "categories": categories,
        "factors": factors,
    }


def get_factor_map() -> dict[str, dict]:
    return {item["id"]: _with_runtime_metadata(item) for item in FACTORS}
