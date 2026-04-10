from __future__ import annotations


def render_shell(title: str, mount_path: str) -> str:
    return f"""
<!doctype html>
<html lang=\"zh-CN\">
  <head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>{title}</title>
    <style>
      :root {{
        --bg-1: #f3efe4;
        --bg-2: #d8e7ef;
        --panel: #fffef9;
        --ink: #1f2528;
        --accent: #0d6e7f;
      }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
        color: var(--ink);
        background: radial-gradient(circle at 20% 20%, var(--bg-2), var(--bg-1));
      }}
      .card {{
        width: min(92vw, 640px);
        background: var(--panel);
        border-radius: 20px;
        padding: 32px;
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.09);
      }}
      h1 {{ margin: 0 0 8px; font-size: 28px; }}
      p {{ margin: 8px 0; line-height: 1.6; }}
      .path {{
        display: inline-block;
        margin-top: 10px;
        padding: 6px 12px;
        border-radius: 999px;
        background: #e4f4f7;
        color: var(--accent);
        font-weight: 600;
      }}
    </style>
  </head>
  <body>
    <section class=\"card\">
      <h1>{title}</h1>
      <p>玻璃工厂数字化平台入口已就绪，前端静态资源可在此路径继续挂载。</p>
      <span class=\"path\">{mount_path}</span>
    </section>
  </body>
</html>
""".strip()
