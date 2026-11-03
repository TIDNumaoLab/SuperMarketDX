// 部門の選択。店長は全部門、担当者は所属部門のみ(GET /api/me の accessible_departments)
import { useAuth } from "../auth/AuthContext";
import pageStyles from "../styles/page.module.css";
import type { DepartmentRef } from "../types/api";

interface Props {
  value: string;
  onChange(code: string): void;
  // 指定するとその業務の部門だけに絞る(在庫入力は生鮮 order のみ など)
  businessType?: DepartmentRef["business_type"];
}

export function selectableDepartments(
  departments: DepartmentRef[],
  businessType?: DepartmentRef["business_type"],
): DepartmentRef[] {
  return businessType ? departments.filter((d) => d.business_type === businessType) : departments;
}

export default function DepartmentSelect({ value, onChange, businessType }: Props) {
  const { me } = useAuth();
  const options = selectableDepartments(me?.accessible_departments ?? [], businessType);
  return (
    <label className={pageStyles.field}>
      部門
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((d) => (
          <option key={d.code} value={d.code}>
            {d.name}
          </option>
        ))}
      </select>
    </label>
  );
}
