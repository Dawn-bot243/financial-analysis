export default function StatTile({
  label,
  value,
  sub,
  hero = false,
}: {
  label: string
  value: string
  sub: string
  hero?: boolean
}) {
  return (
    <div className={hero ? 'stat hero' : 'stat'}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-sub">{sub}</div>
    </div>
  )
}
