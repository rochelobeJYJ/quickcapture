# main.pyw — 콘솔 없이(pythonw) 실행하기 위한 진입점.
# 실제 로직은 main.py 하나로 관리한다 (코드 중복 방지).
from main import main

if __name__ == "__main__":
    main()
