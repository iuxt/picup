## PICUP

替代 picgo 和 piclist 的工具

上传图床到s3存储用的

支持上传、加水印、按年月建文件夹存储图片。

除了这个文件是我写的，其他的都是AI写的。

现在只支持macOS

python 我用的是macOS自带的 3.9  或者使用 3.12 版本，3.9 aws 的库有个警告。


```bash
cp picup.plist ~/Library/LaunchAgents/picup.plist
launchctl load ~/Library/LaunchAgents/picup.plist
launchctl start picup
launchctl stop picup
launchctl unload ~/Library/LaunchAgents/picup.plist
```