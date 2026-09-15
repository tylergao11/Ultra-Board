"""每日增量更新唯一入口：新增日期及必需缺口，沿用本地唯一存储。"""
import sys
from replay_complete import main

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    if '--daily' not in sys.argv:
        sys.argv.append('--daily')
    sys.exit(main())
