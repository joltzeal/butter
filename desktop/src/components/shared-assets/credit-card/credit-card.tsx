import type { CSSProperties } from "react";

import { MastercardIcon, PaypassIcon } from "./icons";
import "./credit-card.css";

export type CreditCardType =
  | "transparent"
  | "transparent-gradient"
  | "brand-dark"
  | "brand-light"
  | "gray-dark"
  | "gray-light"
  | "transparent-strip"
  | "gray-strip"
  | "gradient-strip"
  | "salmon-strip"
  | "gray-strip-vertical"
  | "gradient-strip-vertical"
  | "salmon-strip-vertical";

export interface CreditCardProps {
  /** Issuer name printed top-left. */
  company?: string;
  /** Grouped digits printed along the bottom. */
  cardNumber?: string;
  /** Cardholder name, rendered uppercase. */
  cardHolder?: string;
  /** Expiry printed beside the holder. */
  cardExpiration?: string;
  type?: CreditCardType;
  className?: string;
  /** Rendered width in px. Omit to fill the parent. */
  width?: number;
  /** Renders the dashed "no card" state and hides the digits. */
  empty?: boolean;
}

const STRIP = new Set(["transparent-strip", "gray-strip", "gradient-strip", "salmon-strip"]);
const VSTRIP = new Set([
  "gray-strip-vertical",
  "gradient-strip-vertical",
  "salmon-strip-vertical",
]);

/**
 * Payment card visual, 316×190 intrinsic.
 *
 * The Untitled UI original is Tailwind-only; this is the same API rebuilt on the
 * project's plain CSS so it inherits the theme tokens instead of dragging a
 * framework and its preflight in. Sizing is aspect-ratio based, so callers pass
 * a width (or let it fill) and the art scales without a transform.
 */
export function CreditCard({
  company = "",
  cardNumber = "•••• •••• •••• ••••",
  cardHolder = "",
  cardExpiration = "MM/YY",
  type = "gray-dark",
  className = "",
  width,
  empty = false,
}: CreditCardProps) {
  const style: CSSProperties | undefined = width ? { width } : undefined;
  const last4 = cardNumber.replace(/\s+/g, "").slice(-4);

  return (
    <div
      className={["ccard", `ccard--${type}`, empty ? "ccard--empty" : "", className]
        .filter(Boolean)
        .join(" ")}
      style={style}
      data-empty={empty || undefined}
    >
      {STRIP.has(type) ? <div className="ccard__strip" /> : null}
      {VSTRIP.has(type) ? <div className="ccard__vstrip" /> : null}
      {type === "transparent-gradient" ? (
        <div className="ccard__diffusor">
          <i />
          <i />
          <i />
          <i />
        </div>
      ) : null}

      {empty ? (
        <div className="ccard__empty">
          <span>无付款方式</span>
          <span>读取后显示卡信息</span>
        </div>
      ) : (
        <>
          <div className="ccard__top">
            <span className="ccard__company">{company}</span>
            <PaypassIcon className="ccard__paypass" />
          </div>

          <div className="ccard__bottom">
            <div className="ccard__lines">
              <span className="ccard__pan">•••• •••• •••• {last4}</span>
              <div className="ccard__meta">
                <span className="ccard__holder">{cardHolder || "—"}</span>
                <span className="ccard__exp">{cardExpiration}</span>
              </div>
            </div>
            <MastercardIcon className="ccard__brand" />
          </div>
        </>
      )}
    </div>
  );
}
