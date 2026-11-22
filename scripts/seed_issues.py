#!/usr/bin/env python3
"""把首批 12 条示例知识建成真实 Issue（各带反应），只跑一次。

知识条目必须来自 Issue，`aggregate.py` 才能把它们聚合进 index；
否则下一次聚合会把没有 Issue 支撑的条目清掉。
用法：GITHUB_TOKEN=... python3 scripts/seed_issues.py
"""

import json
import os
import urllib.request

API = "https://api.github.com"
TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ.get("GITHUB_REPOSITORY", "meng587/vqa-rs-kb")
SOURCE = "河北广电 平台运维部 · 2026-11"

SEED = [
    ("矩阵主备切换耗时", "阈值", "矩阵, 主备",
     "万象矩阵单台支持 200 路切换，1+1 主备之间切换约 3 秒，自动返回主路约 5 秒。"
     "判断切换慢时先分清是矩阵内部耗时还是下游解码器重锁耗时：内部切换在秒级以内，"
     "下游重锁通常要 4 到 6 秒，两者不能合成一个总时长去查。", 4),
    ("主备卫星音频编码必须同为 MP2", "规程", "卫星, 音画同步, MP2",
     "卫星主备接收机若主路 MP2、备路 AAC，一旦自动切备就会让老机顶盒音频缓存与本地时钟失配，"
     "表现为声音滞后约 2 秒，而新机顶盒有自适应补偿不受影响。整改只有一条：主备音频编码格式"
     "必须统一为 MP2，禁止主备异构，改完要在接收机侧核对实际输出格式。", 5),
    ("音画不同步先切爱上信源应急", "故障", "音画同步, 应急, 机顶盒",
     "只有老机顶盒用户反馈声音滞后、新机顶盒正常时，先切爱上信源（MP2 格式）应急恢复，"
     "再重启故障频道的卫星信源任务。如果全平台所有机顶盒同时不同步，方向应转查编码器 PTS，"
     "不是卫星链路问题，改信源没有用。", 3),
    ("编码器 PTS 过大导致全平台不同步", "故障", "编码器, PTS, 音画同步",
     "直播编码器 PTS 时间戳过大时，全平台都会音画不同步，与机顶盒型号和信源无关。"
     "这类问题靠切信源、重启任务都压不住，要升级编码器固件；升级后核对版本号，"
     "避免设备重启或回滚又退回旧版本导致复发。", 3),
    ("IGMPv2 querier 丢应答导致矩阵闪断", "故障", "IGMP, 组播, 矩阵闪断",
     "同一 VLAN 下 600 条以上组播流时，直播汇聚交换机的 IGMPv2 snooping querier 处理组播应答"
     "有上限，会丢应答，交换机据此认为矩阵不再需要某组播，端口就断流，过一会儿又自愈。"
     "典型现象是矩阵突然丢几路信号再自行恢复，别先怀疑矩阵硬件。", 5),
    ("IGMPv3 必须交换机和矩阵双侧升级", "规程", "IGMPv3, 升级",
     "IGMPv3 相比 v2 取消了独立 Leave 报文与 Report Suppression，并支持源过滤，"
     "但只有交换机和矩阵双侧都升到 v3 才真正生效；只升一侧会按 v2 降级处理，问题照旧。"
     "升级后两侧版本都要查，不能只看交换机。", 4),
    ("IGMP 版本配成 2 时 v3 报文被广播", "术语", "IGMP, 交换机",
     "交换机的 igmp-snooping 在版本配成 2 时，收到 v3 报文会直接在 VLAN 内广播而不做 snooping 处理。"
     "所以排查不能只看设备是否支持 v3，必须确认当前配置版本，配置版本才是实际生效的版本。", 2),
    ("矩阵分四组各管一段业务", "经验", "矩阵, 分组, 定位",
     "8 台矩阵按 4 组 1+1 主备部署：第一组接爱上信源到央视卫视，第二组接本地信源与地方频道，"
     "第三组给各市县与慢直播，第四组给 DRM 与临时直播。定位问题先确认信号走的是哪一组，"
     "不要跨组比对现象，跨组现象不同不代表故障不同。", 3),
    ("技术中心矩阵无备份属单点风险", "制度", "矩阵, 单点, 变更",
     "技术中心的两台矩阵没有主备，属于单点风险：这两台上的切换与配置变更要避开直播高峰，"
     "变更前先确认可回退路径，并在值班记录里写明变更内容与回退方式，便于交接班时追溯。", 2),
    ("卫星信号差先看天气与极化", "故障", "卫星, 云层, 高频头",
     "夏季云层厚是卫星信号变差的常见诱因，会触发接收机自动切备路；如果主备编码格式不一致，"
     "切换本身就变成二次故障源。天线极化方向与高频头状态要一并检查，更换高频头后信号强度"
     "与信号质量会有明显改善，换完重新记录基线值。", 3),
    ("三选一切换系统已下线不要再查", "经验", "误区, 切换系统",
     "三选一切换系统已经下线，现在所有切换都走 IP 矩阵。遇到切换类问题不要再按三选一链路排查，"
     "也不要把旧链路写进应急预案当备用路径，否则演练时会按已不存在的路径去验证。", 3),
    ("统计频道数必须区分上线停播", "制度", "口径, 统计",
     "统计频道数量必须区分上线、下线、停播三种状态，已下线频道不计入总数，已下线的平台也不参与统计。"
     "口径不统一时同一时段的数字会对不上，所以对数之前先统一口径，再比对差异。", 2),
]


def api(path, method="GET", payload=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "vqa-rs-kb-seed")
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=25) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body.strip() else {}


def main():
    for title, kind, tags, body, stars in SEED:
        text = (
            f"### 标题\n{title}\n\n"
            f"### 类型\n{kind}\n\n"
            f"### 标签\n{tags}\n\n"
            f"### 来源\n{SOURCE}\n\n"
            f"### 正文\n{body}\n"
        )
        issue = api(
            f"/repos/{REPO}/issues",
            "POST",
            {"title": f"[KB] {title}", "body": text, "labels": ["kb-submit"]},
        )
        n = issue["number"]
        for _ in range(stars):
            try:
                api(f"/repos/{REPO}/issues/{n}/reactions", "POST", {"content": "+1"})
            except Exception as e:  # 反应失败不影响发帖
                print(f"#{n} 加星失败：{e}")
        print(f"#{n} {title}")


if __name__ == "__main__":
    main()
