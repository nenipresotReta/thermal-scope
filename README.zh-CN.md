# Thermal Scope

[English](README.md) | [简体中文](README.zh-CN.md)

运行在家庭服务器、NAS 或桌面电脑上的 PT100 温度仪表。一个采集器通过 Wi-Fi 读取兼容温度计，多台手机、平板、电脑共享网页视图。无需云账号、前端构建或额外 Python 包。界面目前为英文，文档提供中英双语。

[版本记录](CHANGELOG.zh-CN.md)。此仓库只包含网页服务，不分发设备固件二进制、Wi-Fi 凭据或私人测量记录。

## 文档与配套项目

- [Thermal Probe](https://github.com/nenipresotReta/thermal-probe)：ESP32 配套固件，只提供源码，需要本地填写 Wi-Fi。仓库目前访问受限，也可按下方协议使用独立实现的兼容设备。
- [部署与恢复](docs/deployment.zh-CN.md)：本地／局域网运行、验收、Docker 备份恢复和排障。
- [参与开发与公开前检查](CONTRIBUTING.zh-CN.md)。

## 本地运行

需要 Python 3.11 或更新版本，在仓库目录执行：

```sh
python3 server.py
```

打开 **http://localhost:8080**，首次通过 DEVICE 连接：

1. 填写温度计 IPv4 地址，TEST 成功后 CONNECT。
2. 或输入局域网网段，例如 `192.168.1.0/24`，DISCOVER 后选择 USE DEVICE。

发现过程同时验证 HTTP 温度端点和 Modbus 数据格式，不把任意 HTTP 服务当作温度计。限制为最多 256 个地址的私有 IPv4 网段，16 路并发。扫描从**服务器**发出，Docker 网络、VLAN 或隔离可能阻止发现。只要地址可达，也可手动连接。

选定地址保存在 `data/device.json`，重启复用。网页不索要温度计 Wi-Fi 密码。连接测试失败时保留原设备；记录或标定结束后才能更换设备。切换后清除实时物理模型历史，避免混合探头数据预测。

可选启动参数：

```sh
python3 server.py --device 192.168.1.100 --port 8080 --data ./data
```

地址优先级：`--device`、已保存选择、`DEVICE_HOST` 初始默认值。当前支持一个活动温度计，不是多设备记录管理器。

## Docker

```sh
cp .env.example .env
docker compose up -d --build
```

默认只绑定本机回环。在可信家庭服务器上，将 `.env` 的 `WEB_BIND` 设为 `0.0.0.0`，其他设备访问 `http://SERVER_IP:8080`。`DEVICE_HOST` 可留空，在网页选择。命名卷 `scope-data` 保存设备选择、SQLite 历史、事件和预测评分。

容器以非 root 用户运行，无需 USB 映射或刷固件。服务器需要访问温度计 TCP 502，发现功能还需要 TCP 80。当前没有登录和 TLS，应限制在预期的可信网络。

## 外观与实时示波视图

THEME 可在 **GitHub Dark** 和 **Paper** 间切换，默认深色，每个浏览器保存并同步到其其他标签页。图表网格、事件、预测阴影和弹窗共同切换。配色参考 [GitHub Primer](https://primer.style/product/primitives/color/)，与温度计显示一致。

- TIME / DIV × 10 决定时间窗口，默认 10 分钟，其中包括 5 分钟未来预测空间。
- LIVE 中滚轮只改变温度上限，即 **0–X°C**；不改变时间窗口、不垂直平移、不暂停采集。
- **0–250°C FIXED** 恢复固定范围；AUTO 根据可见数据自动缩放。HOLD／历史记录中滚轮缩放时间，拖动平移历史。
- HOLD 冻结视图，后台继续采集和存储；LIVE 返回当前值。
- **D1 默认 °C/min，D2 默认 °C/min²**，按钮可切换秒单位，保留已保存的选择。存储和协议仍用秒，显示分别乘 60 和 3600。
- START 开始记录，支持 CHARGE、DRY END、FC START、FC END、SC START、DROP 和自定义事件。DROP 结束记录，后台采集继续。
- ARCHIVE 查看记录并导出 CSV；FORECAST CSV 导出冻结的预测、参数和之后的实际观测。

采集器使用持久 Modbus 连接，目标 10 Hz，实际频率受网络影响。浏览器通过 SSE 共享数据，不各自连接温度计。

## 咖啡与一般记录

START 前选择 COFFEE 或 GENERAL / NON-COFFEE。咖啡模式有阶段标记、发展时间、可选 AUTO DROP；一般模式只有手动事件，没有自动判断和咖啡发展／失重统计。

记录开始后时间轴固定从 **00:00** 起，初始 **16 分钟**，按需扩展以容纳完整记录和预测。LIVE 滚轮仍从零缩放温度；HOLD 可检查历史；ARCHIVE 默认显示整段记录。

FC START 后实时显示发展时间及比例：`(当前时刻 − FC START) / (当前时刻 − 记录开始) × 100%`。DROP 或 STOP 时冻结。分母是记录开始时间，不是后来标记的 CHARGE。手工回溯标记按输入时间保留。

AUTO DROP 是参考 Artisan 行为独立实现的回溯降温检测，不预测理想下豆点，也不控制加热。条件为咖啡记录至少 7 分钟、最近原始温度至少 160°C；半秒原始中值须累计下降至少 3°C，且至少 2 秒斜率不高于 −0.8°C/s。候选等待 **20 秒**，要求净下降至少 15°C；反弹至少 5°C、回到先前峰值附近或采集间隙超过 1 秒时取消。最终 DROP 回溯到之前局部峰值。

可 IGNORE / DISABLE 忽略候选或关闭检测。ARCHIVE → UNDO AUTO DROP 可重开最近一次自动结束的记录并关闭该记录自动判断；样本未删除。已有更新记录时不能重开更早记录。单个温度探头不能区分真实下豆与产生同样温度轨迹的长时间意外拔出；确认延迟只过滤短暂干扰。重启会清除未确认候选，不跨缺测数据补造事件。

已结束的咖啡记录可通过 ADD WEIGHTS / EDIT WEIGHTS 填入烘焙前后克重。失重率为 `(生豆 − 熟豆) / 生豆 × 100%`；两值须大于 0，熟豆不大于生豆。可编辑、清空并持久保存。样本 CSV 仍为原来的七列格式，重量和发展统计通过 `/api/runs` 及 Archive 提供。

## 热力学预测

采用**条件性的等效单节点热平衡**：

```text
C dT/dt = P − G(T − Ta), C > 0, G > 0
τ = C/G, Teq = Ta + P/G
T(t+s) = T(t) + v0 τ [1 − exp(−s/τ)]
```

假设预测区间内热输入 P、传热系数 G 和环境温度 Ta 局部不变，近期连续测量识别等效时间常数和平衡温度，无需手动给工况命名。

所有预测时长属于同一轨迹：升温从下方接近平衡，降温从上方接近平衡，不凭空预测反转。观测到反转后重新识别，不改写旧预测。不能预知之后的火力、风量或探头接触变化。

默认预测 **5 分钟**，约每 10 秒一个点，另包含精确短期评分时长。参数不确定、接近平衡或不符合单节点的瞬态会明确标注。近直线／平稳序列无法唯一识别远期平衡和时间常数；无法确定有限时间常数时采用恒定净热量极限，物理上不合理的长期外推不显示。

模型针对**平滑后的探头读数**，包含未分离的探头和平滑滞后，不等于真实豆芯温度，也不独立识别热容、功率或环境温度。阴影是参数／残差敏感性范围，**不是经过校准的置信区间**。单次升降温实验不能证明五分钟预测精度。

预测及参数当时冻结，在 +5、10、20、30、60、180、300 秒与实测评分。仅跨不超过 0.5 秒的测量间隙插值。旧模型版本不计入当前模型评分。

## 可选探头响应测试

CALIBRATE 用于室温与充分混合热水之间的阶跃。选目标 WATER 或 AIR，移动探头前开始，稳定后 FINISH & FIT。需要足够温差、时长和响应质量，不合格时可继续或取消。

空气与水结果分别保存，不自动补偿温度或覆盖有效预测模型。这测量响应时间，不是温度偏置／增益标定；外壳尺寸不能单独确定完整内部响应。

## 兼容温度计协议

- TCP 502，unit 1，功能码 3，寄存器从零开始。
- 四个有限大端 Float32：寄存器对 0 为原始 °C、2 为平滑 °C、4 为 D1 °C/s、6 为 D2 °C/s²。
- 一次读 0–7 返回 16 字节；异常码 4 按传感器不可用／预热处理。
- 发现还验证 TCP 80 的 `GET /api/temperature`，字段为 `valid`、`derivatives_ready`、`time_s`、`raw_c`、`temperature_c`、`d1_c_per_s`、`d2_c_per_s2`。

导数平滑由设备完成，原目标约为 10 秒二次拟合；应用保留接收值，不悄悄重新计算另一套导数。

## 存储和限制

SQLite WAL 约每秒提交，突然断电可能丢失最近未提交样本。时间戳来自服务器接收时刻，不是硬件采样时间。浏览器重连会恢复共享记录状态并补载已存历史，即使探头离线也可以。实时计时、数据新鲜度和发展比例采用服务器时间结合浏览器单调时钟，观看设备的系统时间偏差不会改变比例。

每个数据库只运行一个采集进程。没有自动保留／删除策略，需要监测磁盘。运行中本地一致性备份示例：

```sh
python3 -c "import sqlite3; a=sqlite3.connect('data/scope.sqlite3'); b=sqlite3.connect('backup.sqlite3'); a.backup(b); b.close(); a.close()"
```

迁移数据库到 Docker 卷前先停止采集，数据目录须允许 UID/GID 10001 写入。不能只复制正在运行的 WAL 数据库主文件。换设备保留历史，应另开记录。预测仅与发出它的设备地址对应的样本评分；旧的无来源预测保留，但不把待评分项分配给新设备。CSV 分块导出，可能被表格软件视为公式的事件名只在导出时转义。

## 开发与发布检查

```sh
python3 -m unittest discover -s tests -v
for test in tests/*.test.js; do node "$test"; done
for file in static/*.js; do node --check "$file"; done
python3 tools/check_release.py
docker compose config -q
```

Node 只用于开发检查，运行时不需要。测试覆盖发现、配置持久化、Modbus 分包／重连、事件／CSV、热模型和预测评分；GitHub Actions 执行测试、暂存源码检查及全新容器启动验收。

发布检查针对暂存快照，拒绝设备固件、二进制、运行数据库、截图和检测到的凭据。`.gitignore`、`.dockerignore` 排除本地运行材料；这些措施不能替代历史及发布附件的人工审查。

参考：[Artisan 图表实现](https://github.com/artisan-roaster-scope/artisan/blob/master/src/artisanlib/canvas.py)、[自动 DROP 说明](https://github.com/artisan-roaster-scope/artisan/discussions/1159)、[MIT 集总热分析](https://web.mit.edu/16.unified/www/FALL/thermodynamics/notes/node129.html)。项目独立实现，不包含 Artisan 源码。

## 许可证

[MIT](LICENSE)。详见[第三方声明](THIRD_PARTY_NOTICES.zh-CN.md)。
