window.GFMobile = (() => {
  const createIdempotencyKey = () => {
    if (window.crypto && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return "gf-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  };

  const unwrapEnvelope = (payload) => {
    if (payload && typeof payload === "object" && "data" in payload) {
      return payload.data;
    }
    return payload;
  };

  const request = async (url, options = {}, token = "") => {
    const headers = { ...(options.headers || {}) };
    if (token) {
      headers.Authorization = "Bearer " + token;
    }
    const body = options.body;
    if (body && !(body instanceof FormData) && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(url, {
      credentials: "include",
      ...options,
      headers,
    });
    const contentType = response.headers.get("content-type") || "";
    const isJson = contentType.includes("application/json");
    const payload = isJson ? await response.json() : await response.text();
    if (!response.ok) {
      const message = isJson ? (payload.message || payload.error || JSON.stringify(payload)) : String(payload);
      throw new Error(message || "Request failed");
    }
    return unwrapEnvelope(payload);
  };

  const formatDateTime = (value) => {
    if (!value) return "--";
    try {
      return new Date(value).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return String(value);
    }
  };

  const formatMoney = (value) => {
    const num = Number(value || 0);
    return new Intl.NumberFormat("zh-CN", {
      style: "currency",
      currency: "CNY",
      maximumFractionDigits: 2,
    }).format(num);
  };

  const safeArray = (value) => Array.isArray(value) ? value : [];

  const statusLabel = (status) => ({
    pending: "待处理",
    received: "已接单",
    confirmed: "已确认",
    entered: "已录入",
    in_production: "生产中",
    producing: "加工中",
    completed: "已完工",
    produced: "已生产",
    ready_for_pickup: "可提货",
    shipping: "运输中",
    picked_up: "已提货",
    delivered: "已送达",
    cancelled: "已取消",
    unpaid: "未收款",
    partial: "部分付款",
    overdue: "逾期",
    paid: "已结清",
    pass: "合格",
    fail: "不合格",
    in_progress: "进行中",
  }[status] || (status || "--"));

  const statusTone = (status) => {
    if (["pending", "received"].includes(status)) return "pending";
    if (["confirmed", "entered"].includes(status)) return "confirmed";
    if (["in_production", "producing", "in_progress"].includes(status)) return "in_production";
    if (["completed", "produced", "picked_up", "delivered", "paid"].includes(status)) return "completed";
    if (["ready_for_pickup", "shipping", "partial"].includes(status)) return "ready_for_pickup";
    if (["cancelled", "overdue", "fail", "unpaid"].includes(status)) return "cancelled";
    return "pending";
  };

  const initials = (name) => (name || "G").trim().slice(0, 1).toUpperCase();

  const downloadDocument = async ({ url, token, filename }) => {
    const response = await fetch(url, {
      credentials: "include",
      headers: token ? { Authorization: "Bearer " + token } : {},
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename || "document.pdf";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  };

  const installSignaturePad = (canvas) => {
    const ctx = canvas.getContext("2d");
    const resize = () => {
      const ratio = Math.max(window.devicePixelRatio || 1, 1);
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * ratio;
      canvas.height = rect.height * ratio;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(ratio, ratio);
      ctx.lineWidth = 2.2;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#243247";
    };
    resize();
    let drawing = false;
    let hasStroke = false;
    const point = (event) => {
      const rect = canvas.getBoundingClientRect();
      const touch = event.touches ? event.touches[0] : event;
      return { x: touch.clientX - rect.left, y: touch.clientY - rect.top };
    };
    const start = (event) => {
      drawing = true;
      hasStroke = true;
      const p = point(event);
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      event.preventDefault();
    };
    const move = (event) => {
      if (!drawing) return;
      const p = point(event);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      event.preventDefault();
    };
    const end = () => { drawing = false; };
    canvas.addEventListener("mousedown", start);
    canvas.addEventListener("mousemove", move);
    window.addEventListener("mouseup", end);
    canvas.addEventListener("touchstart", start, { passive: false });
    canvas.addEventListener("touchmove", move, { passive: false });
    window.addEventListener("touchend", end, { passive: false });
    return {
      clear() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        hasStroke = false;
      },
      toDataUrl() {
        return hasStroke ? canvas.toDataURL("image/png") : "";
      },
      hasStroke() {
        return hasStroke;
      },
      resize,
    };
  };

  return {
    createIdempotencyKey,
    request,
    formatDateTime,
    formatMoney,
    safeArray,
    statusLabel,
    statusTone,
    initials,
    downloadDocument,
    installSignaturePad,
  };
})();
