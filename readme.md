## PICUP

替代 picgo 和 piclist 的工具

上传图床到s3存储用的

支持上传、加水印、按年月建文件夹存储图片。

除了这个文件是我写的，其他的都是AI写的。

现在只支持macOS

python 我用的是macOS自带的 3.9  或者使用 3.12 版本，3.9 aws 的库有个警告。

安装依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

本地启动：

```bash
./picup
```

服务会用 Waitress 启动，不再使用 Flask 开发服务器。默认监听 `127.0.0.1:36677`，可以在 `.env` 里修改：

```env
PICUP_HOST=127.0.0.1
PICUP_PORT=36677
PICUP_THREADS=4
```

注册到系统，并设置为 macOS 开机自启动：

```bash
./install.sh
```

取消 macOS 开机自启动，并取消注册。
```bash
./uninstall.sh
```
