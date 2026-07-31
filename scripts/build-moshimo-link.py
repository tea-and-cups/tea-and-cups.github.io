import sys
import urllib.parse

A_ID = "5712884"
P_ID = "54"
PC_ID = "54"
PL_ID = "616"


def build(url):
    encoded = urllib.parse.quote(url, safe="")
    return (
        f"https://af.moshimo.com/af/c/click?a_id={A_ID}&p_id={P_ID}"
        f"&pc_id={PC_ID}&pl_id={PL_ID}&url={encoded}"
    )


def main():
    urls = sys.argv[1:]
    if not urls:
        print("usage: python site/scripts/build-moshimo-link.py <url1> [<url2> ...]")
        sys.exit(1)
    for url in urls:
        print(build(url))


if __name__ == "__main__":
    main()
