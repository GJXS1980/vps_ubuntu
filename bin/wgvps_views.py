"""Server-rendered views shared by full and partial admin responses."""
from html import escape
from urllib.parse import parse_qs, urlencode
from datetime import datetime, timezone

STATES = {"online": "在线", "offline": "离线", "never": "尚无握手", "unknown": "状态未知", "disabled": "已停用"}
PAGES = {"/admin": "客户管理", "/admin/status": "连接监控", "/admin/groups": "分组管理", "/admin/logs": "操作日志"}


def options(values, selected):
    return "".join(f'<option value="{escape(k)}"{" selected" if k == selected else ""}>{escape(v)}</option>'
                   for k, v in values)


def post(csrf, body, attrs=""):
    return (f'<form method="post" action="/admin" {attrs}><input type="hidden" name="csrf" value="{csrf}">'
            + body + '</form>')


def button(action, text):
    return f'<button name="action" value="{action}">{text}</button>'


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if value else "未知"


def traffic(n):
    if n is None:
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:g} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def cells(r, groups):
    age = r["age"]
    return dict(label=escape(r["label"]), name=r["name"], group=escape(groups.get(r.get("group"), "未分组")),
                address=escape(r["address"]), enabled="已启用" if r["enabled"] else "已禁用",
                status=f'<span class="pill {r["status"]}">{STATES[r["status"]]}</span>',
                age="—" if age is None else f"{age} 秒前" if age < 60 else f"{age // 60} 分钟前",
                rx=traffic(r.get("rx")), tx=traffic(r.get("tx")), endpoint=escape(r.get("endpoint") or "—"))


def drawer(r, groups, csrf, stamp, close):
    d = cells(r, groups)
    name = r["name"]
    hidden = f'<input type="hidden" name="user" value="{name}">'
    controls = (button("bundle", "配置下载与二维码") + button("issue", "签发领取链接") + button("disable", "禁用客户")
                if r["enabled"] else button("enable", "启用客户") + button("confirm-delete", "删除客户…"))
    detail = [("客户编号",name), ("隧道 IPv4",d["address"]), ("分组",d["group"]), ("管理状态",d["enabled"]),
              ("连接状态",d["status"]), ("最近握手",d["age"]), ("Endpoint",d["endpoint"]),
              ("服务器接收 / 发送",d["rx"]+" / "+d["tx"]), ("创建时间",timestamp(r.get("created"))),
              ("公钥摘要",escape(r.get("fingerprint","—"))), ("最后刷新",timestamp(stamp))]
    return (f'<aside class="drawer" aria-label="客户详情"><a data-view href="{close}">关闭详情 ×</a>'
            f'<h2>{d["label"]}</h2><dl>' + "".join(f'<dt>{k}</dt><dd>{v}</dd>' for k,v in detail) + '</dl>'
            + post(csrf, hidden + controls + button("confirm-rotate","轮换密钥…"))
            + post(csrf, hidden + '<label>新名称<input required name="label" maxlength="40"></label>'+button("rename","保存名称"))
            + post(csrf, hidden + '<label>所属分组<select name="group">'+options(groups.items(), r.get("group",""))
                   + '</select></label>'+button("assign","保存分组")) + '</aside>')


def directory(snapshot, query, csrf, path):
    rows, groups = snapshot["rows"], {"":"未分组", **snapshot["groups"]}
    args = {k:v[0] for k,v in parse_qs(query, keep_blank_values=True, max_num_fields=16).items()}
    def url(**changes):
        return escape(path + "?" + urlencode({k:v for k,v in (args | changes).items() if v != "" or k=="group"}))
    stats = [('客户总数',len(rows)),('已启用',sum(r['enabled'] for r in rows))]
    stats += [(STATES[k],sum(r['status']==k for r in rows)) for k in ('online','offline','never')]
    stats_html = '<div class="stats">' + ''.join(f'<span>{k}<b>{v}</b></span>' for k,v in stats) + '</div>'
    group_options = list(groups.items())
    if path == "/admin/groups":
        rows_html = []
        for gid,label in group_options:
            members = [r for r in rows if r.get("group","")==gid]
            edit = ""
            if gid:
                hidden = f'<input type="hidden" name="group" value="{gid}">'
                edit = post(csrf, hidden+'<input aria-label="新组名" name="label" maxlength="40" required>'+button("group-rename","改名"))
                if not members:
                    edit += post(csrf,hidden+button("group-delete","删除空组"))
            rows_html.append(f'<tr><td>{escape(label)}</td><td>{len(members)}</td><td>{sum(r["status"]=="online" for r in members)}</td><td>{edit}</td></tr>')
        return (post(csrf,'<label>新分组名称<input required maxlength="40" name="label"></label>'+button("group-create","创建分组"),'class="tools"')
                + table(["分组","客户数","在线数","操作"],rows_html))
    cols = dict(label="客户名称",name="编号",group="分组",address="隧道 IPv4",enabled="启用状态",status="连接状态",
                age="最近握手",rx="服务器接收",tx="服务器发送")
    monitor = path == "/admin/status"
    if monitor:
        cols["endpoint"]="Endpoint"
    q = args.get("q","").strip().casefold()
    selected = args.get("status","")
    enabled = args.get("enabled","")
    group = args.get("group","*")
    hits = [r for r in rows if (not selected or r["status"]==selected)
            and (not enabled or r["enabled"]==(enabled=="yes"))
            and (group=="*" or r.get("group","")==group)
            and any(q in t.casefold() for t in (r["name"],r["label"],r["address"],groups.get(r.get("group"),"未分组")))]
    key = args.get("sort","name")
    if key not in cols:
        key="name"
    def order(r):
        if key=="group": return groups.get(r.get("group"),"未分组").casefold()
        if key=="name": return int(r["name"][4:])
        if key=="address": return tuple(map(int,r["address"].split(".")))
        value=r.get(key)
        return value.casefold() if isinstance(value,str) else value
    present=[r for r in hits if order(r) is not None]
    hits=sorted(present,key=order,reverse=args.get("dir")=="desc")+[r for r in hits if order(r) is None]
    size=int(args.get("size","20")) if args.get("size") in ("20","50","100") else 20
    pages=max(1,(len(hits)+size-1)//size)
    number = args.get("page", "1")
    page = min(pages, max(1, int(number))) if number.isascii() and number.isdigit() and len(number)<7 else 1
    search = (f'<form class="filters" method="get" action="{path}"><label>查找客户<input name="q" value="{escape(args.get("q",""))}" placeholder="名称、编号、IP 或分组"></label>'
              +select("status","连接", [("","全部连接")]+[(k,v) for k,v in STATES.items() if k!="disabled"],selected)
              +select("enabled","启用状态",[("","全部"),("yes","已启用"),("no","已禁用")],enabled)
              +select("group","分组",[("*","全部分组")]+group_options,group if group else "")
              +select("size","每页",[(s,s) for s in ("20","50","100")],str(size))
              +f'<input type="hidden" name="page" value="{page}"><input type="hidden" name="sort" value="{key}"><input type="hidden" name="dir" value="{"desc" if args.get("dir")=="desc" else "asc"}">'
              +f'<button>查询 / 刷新</button><a data-view href="{path}">重置</a></form>')
    heads = [] if monitor else ['<input type="checkbox" id="all" aria-label="选择本页">']
    heads += [f'<a data-view href="{url(sort=k,dir="desc" if key==k and args.get("dir")!="desc" else "asc",page=1)}">{v}{" ↓" if key==k and args.get("dir")=="desc" else " ↑" if key==k else ""}</a>' for k,v in cols.items()]
    rendered=[]
    for r in hits[(page-1)*size:page*size]:
        d=cells(r,groups)
        check='' if monitor else f'<td><input class="pick" type="checkbox" value="{r["name"]}" aria-label="选择 {r["name"]}"></td>'
        rendered.append('<tr>'+check+''.join(f'<td>{d[k]}</td>' for k in cols)
                        +f'<td><a data-view href="{url(customer=r["name"])}">管理</a></td></tr>')
    toolbar=""
    if not monitor:
        toolbar = '<div class="actionbar">' + post(csrf,'<label>客户名称<input required name="label" maxlength="40"></label>'+select("group","所属分组",group_options,"")
                       +button("add","新增客户"),'class="tools"') + post(csrf,button("archive","下载全部配置 ZIP")) + "</div>"
        batch = ('<span id="count">已选 0 人</span><input type="hidden" name="ids" id="ids">'
                 +select("group","目标分组",group_options,"") + ''.join(button("batch-"+k,v) for k,v in
                 [("group","移动到分组"),("enable","批量启用"),("disable","批量禁用"),("export","导出所选 ZIP")]))
        search+=post(csrf,batch,'class="tools" id="batch"')
    foot=f'<div class="pager">匹配 {len(hits)} 人 · 第 {page} / {pages} 页 '
    if page>1: foot+=f'<a data-view href="{url(page=page-1)}">上一页</a> '
    if page<pages: foot+=f'<a data-view href="{url(page=page+1)}">下一页</a>'
    focus=next((r for r in rows if r["name"]==args.get("customer")),None)
    note=f'最近 {snapshot["window"]} 秒有握手记为在线 · 服务器累计流量 · 30 秒自动刷新 · {timestamp(snapshot["time"])}'
    if snapshot.get("warning"): note += " · "+escape(snapshot["warning"])
    return (stats_html+toolbar+search+f'<p class="hint">{note}</p>'+table(heads+["操作"],rendered)+foot+'</div>'
            +(drawer(focus,groups,csrf,snapshot["time"],url(customer="")) if focus else ""))


def select(name, title, items, current):
    return f'<label>{title}<select name="{name}">{options(items,current)}</select></label>'


def table(headers, rows):
    empty=f'<tr><td colspan="{len(headers)}">没有匹配的记录</td></tr>'
    return ('<div class="sheet" tabindex="0"><table><thead><tr>'+''.join(f'<th>{h}</th>' for h in headers)
            +'</tr></thead><tbody>'+(''.join(rows) or empty)+'</tbody></table></div>')
