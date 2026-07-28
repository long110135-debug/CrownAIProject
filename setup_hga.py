#!/usr/bin/env python3
"""
皇冠AI赛事研判系统 - 皇冠账号设置
首次使用前运行此脚本，将账号密码存入macOS钥匙串
"""
import sys
import os
import getpass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.hga_scraper import save_hga_credentials, get_hga_credentials, HGACrownScraper


def main():
    print("\n" + "=" * 50)
    print("  皇冠AI - 账号设置")
    print("  账号密码将安全存储在macOS钥匙串中")
    print("=" * 50 + "\n")

    # 检查是否已有配置
    existing_user, existing_pass = get_hga_credentials()
    if existing_user:
        print(f"当前已配置账号: {existing_user[:3]}***")
        answer = input("是否要更新？(y/N): ").strip().lower()
        if answer != "y":
            print("保持现有配置。")
            return

    # 输入新账号
    print("\n请输入皇冠平台(hga050.com)的登录信息：")
    username = input("  账号: ").strip()
    password = getpass.getpass("  密码: ").strip()

    if not username or not password:
        print("错误: 账号和密码不能为空")
        return

    # 保存到钥匙串
    save_hga_credentials(username, password)
    print(f"\n✓ 账号 {username[:3]}*** 已保存到macOS钥匙串")

    # 测试登录
    print("\n正在测试登录...")
    scraper = HGACrownScraper()
    success = scraper.login(username, password)
    scraper.close()

    if success:
        print("✓ 登录测试成功！系统可以正常获取盘口数据。")
    else:
        print("⚠ 登录测试未通过，请检查账号密码是否正确。")
        print("  (也可能是网络问题，稍后可在main.py运行时自动重试)")

    print("\n设置完成。现在可以运行 main.py 进行每日分析了。")


if __name__ == "__main__":
    main()
