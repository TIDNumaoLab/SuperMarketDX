// まだ作っていない画面の仮置き(段階2以降で置き換える)
import styles from "../styles/page.module.css";

interface Props {
  title: string;
}

export default function PlaceholderPage({ title }: Props) {
  return (
    <section>
      <h1>{title}</h1>
      <div className={styles.panel}>
        <p style={{ margin: 0 }}>この画面は準備中です。</p>
      </div>
    </section>
  );
}
