import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Account, Api, BillingForm } from "../api/client";
import { useOptionalApi, useRealtime } from "./useRealtime";
import { useToasts } from "./useToasts";

const KEY = ["accounts"] as const;

export function useAccounts() {
  const api = useOptionalApi();
  const { state } = useRealtime();
  return useQuery({
    queryKey: KEY,
    queryFn: () => api!.listAccounts(),
    enabled: state === "online" && Boolean(api),
    refetchOnWindowFocus: false,
  });
}

export function useAccountActions() {
  // Actions are only reachable from views rendered after the boot gate, so the
  // API instance is guaranteed; the assertion keeps hook order stable.
  const api = useOptionalApi() as Api;
  const qc = useQueryClient();
  const { push } = useToasts();

  const invalidate = () => qc.invalidateQueries({ queryKey: KEY });

  const create = useMutation({
    mutationFn: (payload: { email: string; password?: string; note?: string }) => api.createAccount(payload),
    onSuccess: (account: Account) => {
      invalidate();
      push({ kind: "ok", title: "账号已添加", detail: account.email });
    },
    onError: (err: Error) => push({ kind: "error", title: "添加失败", detail: err.message }),
  });

  const update = useMutation({
    mutationFn: ({ email, ...patch }: { email: string; password?: string; note?: string }) =>
      api.updateAccount(email, patch),
    onSuccess: () => invalidate(),
    onError: (err: Error) => push({ kind: "error", title: "更新失败", detail: err.message }),
  });

  const remove = useMutation({
    mutationFn: (email: string) => api.deleteAccount(email),
    onSuccess: () => {
      invalidate();
      push({ kind: "info", title: "账号已删除" });
    },
    onError: (err: Error) => push({ kind: "error", title: "删除失败", detail: err.message }),
  });

  const login = useMutation({
    mutationFn: (payload: { email: string; password?: string; note?: string; code_url?: string }) =>
      api.login(payload),
    onSuccess: (result) => {
      invalidate();
      push({
        kind: result.ok ? "ok" : "error",
        title: result.ok ? "登录成功" : "登录未完成",
        detail: result.ok ? result.account.email : result.message,
      });
    },
    onError: (err: Error) => push({ kind: "error", title: "登录异常", detail: err.message }),
  });

  const bulkImport = useMutation({
    mutationFn: (text: string) => api.bulkImport(text),
    onSuccess: (result) => {
      invalidate();
      push({
        kind: result.ok ? "ok" : "error",
        title: result.ok ? "批量导入完成" : "批量导入未执行",
        detail: result.message,
      });
    },
    onError: (err: Error) => push({ kind: "error", title: "导入异常", detail: err.message }),
  });

  const reloginBatch = useMutation({
    mutationFn: (emails?: string[]) => api.batchRelogin(emails),
    onSuccess: (result) => {
      invalidate();
      push({ kind: "ok", title: "批量重登完成", detail: `处理 ${result.count} 个账号` });
    },
    onError: (err: Error) => push({ kind: "error", title: "批量重登失败", detail: err.message }),
  });

  const checkSessions = useMutation({
    mutationFn: (emails?: string[]) => api.checkSessions(emails),
    onSuccess: (result) => {
      invalidate();
      const offline = result.results.filter((r) => !r.ok).length;
      push({
        kind: offline ? "info" : "ok",
        title: "会话检测完成",
        detail: `${result.results.length} 个账号，${offline} 个掉线`,
      });
    },
    onError: (err: Error) => push({ kind: "error", title: "检测失败", detail: err.message }),
  });

  const fetchBilling = useMutation({
    mutationFn: (email: string) => api.getBilling(email),
    onSuccess: (result) => {
      invalidate();
      if (!result.ok) {
        push({ kind: "error", title: "读取账单失败", detail: result.message });
        return;
      }
      const info = result.info;
      if (!info) {
        push({ kind: "info", title: "账单已读取", detail: "没有返回账单内容" });
        return;
      }
      const detail = info.has_card
        ? `${info.display_card_type || "银行卡"} · 尾号 ${info.card_suffix || "----"}${
            info.expiry ? ` · ${info.expiry}` : ""
          }`
        : "该账号还没有绑定付款方式";
      push({ kind: "ok", title: "账单已读取", detail });
    },
    onError: (err: Error) => push({ kind: "error", title: "读取账单失败", detail: err.message }),
  });

  const saveBilling = useMutation({
    mutationFn: ({ email, form }: { email: string; form: BillingForm }) => api.putBilling(email, form),
    onSuccess: (result) => {
      invalidate();
      push({
        kind: result.ok ? "ok" : "error",
        title: result.ok ? "账单已保存" : "账单被拒绝",
        detail: result.message,
      });
    },
    onError: (err: Error) => push({ kind: "error", title: "保存失败", detail: err.message }),
  });

  const removeBilling = useMutation({
    mutationFn: (email: string) => api.deleteBilling(email),
    onSuccess: (result) => {
      invalidate();
      push({ kind: result.ok ? "ok" : "error", title: result.ok ? "账单已移除" : "移除失败", detail: result.message });
    },
    onError: (err: Error) => push({ kind: "error", title: "移除失败", detail: err.message }),
  });

  const hsa2 = useMutation({
    mutationFn: ({ email, code }: { email: string; code: string }) => api.submitHsa2(email, code),
    onError: (err: Error) => push({ kind: "error", title: "验证码提交失败", detail: err.message }),
  });

  return {
    create,
    update,
    remove,
    login,
    bulkImport,
    reloginBatch,
    checkSessions,
    fetchBilling,
    saveBilling,
    removeBilling,
    hsa2,
  };
}
