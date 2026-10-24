# 部署与恢复

[English](deployment.md) | [简体中文](deployment.zh-CN.md)

Thermal Scope 是服务器／浏览器应用，[Thermal Probe](https://github.com/nenipresotReta/thermal-probe) 是 ESP32 配套固件，各自不需要对方的构建工具。服务器读温度计，浏览器读服务器，不直接连接 ESP32。

## 部署方式

| 场景 | 启动 | 访问 |
|---|---|---|
| 单机 | `python3 server.py` | `http://localhost:8080` |
| 可信局域网，无 Docker | `python3 server.py --bind 0.0.0.0` | `http://SERVER_IP:8080` |
| Docker 本机访问 | `docker compose up -d --build` | `http://localhost:8080` |
| Docker 局域网 | `.env` 中设 `WEB_BIND=0.0.0.0` 后启动 Compose | `http://SERVER_IP:WEB_PORT` |

先克隆／检出目标版本，在仓库根目录执行。Python 运行时需 3.11+，Node 仅用于开发测试。Docker 需要 Engine 和 Compose 插件，镜像从源码构建，不假定已有公开镜像。

## 首次验收

1. 启动并打开网页，DEVICE 应提供手动 IPv4 和发现。
2. TEST 后 CONNECT，刚开机时等待导数预热。
3. 检查温度、D1/D2 和采样时间持续更新；发现从服务器网络发起。
4. 创建短 GENERAL 记录，加事件、STOP，在 ARCHIVE 查看并导出 CSV，核对时长和事件。
5. 重启服务器，确认记录和设备选择仍保留。

Docker 健康状态只证明 HTTP 应答，温度计连接需在网页另外检查。

## 设置

| 参数 | 含义 |
|---|---|
| `.env` 的 `WEB_BIND` | Docker 发布端口的主机接口，默认回环 |
| `.env` 的 `WEB_PORT` | 主机网页端口，默认 8080 |
| `DEVICE_HOST` | 初始候选温度计地址，可留空 |
| `POLL_INTERVAL` | 目标采集间隔秒数，默认 0.1 |
| 本地 `--bind`、`--port`、`--data`、`--interval` | 监听接口、端口、数据目录、采集间隔 |
| 本地 `--device` | 强制启动设备地址 |

设备优先级为 `--device`、已保存的 `data/device.json`、`DEVICE_HOST`。改环境变量不会覆盖已保存选择；结束记录／标定后通过 DEVICE 切换。Docker 数据卷挂载 `/data`。

服务器须能访问探头 TCP 502，发现还需 TCP 80；浏览器仅需服务器网页端口。应用没有登录、授权和 TLS，共享／不可信网络应另设访问控制，不能直接转发到互联网。

## Docker 备份与恢复

完整一致性备份前，先结束记录／标定并停服务。以下临时容器通过标准输出生成归档，不需要主机目录挂载：

```sh
mkdir -p backups
chmod 700 backups
umask 077
docker compose stop thermal-scope
docker compose run --rm --no-deps -T thermal-scope python -c   'import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode="w|"); t.add("/data",arcname="data"); t.close()' > backups/scope-data.tar
docker compose up -d
```

检查命令退出状态及归档内容。它包含私人记录和设备配置，勿纳入 Git，并限制访问。除非确实要删除数据卷，不要执行 `docker compose down -v`。

把**自己可信的备份**恢复到空／新数据卷前，先停服务。恢复可能覆盖文件，验证完成前保留旧卷／备份：

```sh
docker compose stop thermal-scope
docker compose run --rm --no-deps -T thermal-scope python -c   'import sys,tarfile; t=tarfile.open(fileobj=sys.stdin.buffer,mode="r|*"); t.extractall("/",filter="data")' < backups/scope-data.tar
docker compose up -d
```

归档结构为 `data/...`，恢复到 `/data`，文件须允许 UID/GID 10001 写入。访问已有卷时使用原 Compose 项目名／目录。恢复后核对 ARCHIVE 和设备选择。README 的 SQLite 在线备份只包含数据库，不含设备选择。

## 升级和故障

结束记录、备份、保留旧源码／镜像，再检出新版并执行 `docker compose up -d --build`。验证 HTTP 和实际采集。数据库迁移后旧程序可能不兼容；回滚应同时恢复对应的升级前备份，并接受升级后记录丢失。

| 现象 | 检查 |
|---|---|
| 其他设备打不开 | 回环／局域网绑定、主机端口、防火墙 |
| 发现为空 | 服务器子网、路由／VLAN／隔离，尝试手动地址 |
| 已连接但无读数 | 导数预热、传感器有效性、Modbus 格式 |
| 曲线中断 | 探头／网络、服务器资源／磁盘，检查简短脱敏日志 |
| 容器健康但没读数 | HTTP 健康不等于设备连接正常 |
| 重部署后记录不见 | Compose 项目／卷身份及 `/data` 挂载，勿覆盖原卷初始化 |

每个数据库只支持一个采集器和一个活动探头。没有自动保留策略，应关注磁盘增长并备份重要记录。
