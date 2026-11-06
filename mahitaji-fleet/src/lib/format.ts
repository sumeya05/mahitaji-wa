/** 254712345678 -> 0712 345 678 */
export function localPhone(msisdn: string | null | undefined) {
  if (!msisdn) return '';
  const digits = msisdn.replace(/\D/g, '');
  const local = digits.startsWith('254') ? `0${digits.slice(3)}` : digits;
  return local.length === 10 ? `${local.slice(0, 4)} ${local.slice(4, 7)} ${local.slice(7)}` : msisdn;
}

/** 3000 -> "3 t (3,000 kg)", 150 -> "150 kg" */
export function capacity(kg: number) {
  const plain = `${kg.toLocaleString('en-KE')} kg`;
  return kg >= 1000 && kg % 100 === 0 ? `${(kg / 1000).toLocaleString('en-KE')} t (${plain})` : plain;
}

export function coordinates(latitude: number, longitude: number) {
  return `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;
}
