//! `np.random.default_rng(seed)`: SeedSequence and PCG64 with the same draws, bit for bit.

const INIT_A: u32 = 0x43b0_d7e5;
const MULT_A: u32 = 0x931e_8875;
const INIT_B: u32 = 0x8b51_f9dd;
const MULT_B: u32 = 0x58f3_8ded;
const MIX_L: u32 = 0xca01_f9dd;
const MIX_R: u32 = 0x4973_f715;
const POOL: usize = 4;
const PCG_MULT: u128 = (2549297995355413924u128 << 64) + 4865540595714422341u128;

fn hashmix(mut value: u32, constant: &mut u32) -> u32 {
    value ^= *constant;
    *constant = constant.wrapping_mul(MULT_A);
    value = value.wrapping_mul(*constant);
    value ^ (value >> 16)
}

fn mix(x: u32, y: u32) -> u32 {
    let result = MIX_L.wrapping_mul(x).wrapping_sub(MIX_R.wrapping_mul(y));
    result ^ (result >> 16)
}

fn seed_words(seed: u64) -> [u64; 4] {
    let low = seed as u32;
    let high = (seed >> 32) as u32;
    let entropy: &[u32] = if high == 0 { &[low] } else { &[low, high] };
    let mut constant = INIT_A;
    let mut pool = [0u32; POOL];
    for (i, slot) in pool.iter_mut().enumerate() {
        *slot = hashmix(entropy.get(i).copied().unwrap_or(0), &mut constant);
    }
    for source in 0..POOL {
        for target in 0..POOL {
            if source != target {
                pool[target] = mix(pool[target], hashmix(pool[source], &mut constant));
            }
        }
    }
    let mut constant = INIT_B;
    let mut words = [0u32; 8];
    for (i, word) in words.iter_mut().enumerate() {
        let mut value = pool[i % POOL] ^ constant;
        constant = constant.wrapping_mul(MULT_B);
        value = value.wrapping_mul(constant);
        *word = value ^ (value >> 16);
    }
    let pair = |i: usize| words[i] as u64 | (words[i + 1] as u64) << 32;
    [pair(0), pair(2), pair(4), pair(6)]
}

pub struct Rng {
    state: u128,
    increment: u128,
    spare: Option<u32>,
}

impl Rng {
    pub fn new(seed: u64) -> Rng {
        let words = seed_words(seed);
        let initial = (words[0] as u128) << 64 | words[1] as u128;
        let sequence = (words[2] as u128) << 64 | words[3] as u128;
        let mut rng = Rng { state: 0, increment: sequence << 1 | 1, spare: None };
        rng.step();
        rng.state = rng.state.wrapping_add(initial);
        rng.step();
        rng
    }

    fn step(&mut self) {
        self.state = self.state.wrapping_mul(PCG_MULT).wrapping_add(self.increment);
    }

    fn next_u64(&mut self) -> u64 {
        self.step();
        let mixed = (self.state >> 64) as u64 ^ self.state as u64;
        mixed.rotate_right((self.state >> 122) as u32)
    }

    fn next_u32(&mut self) -> u32 {
        if let Some(value) = self.spare.take() {
            return value;
        }
        let value = self.next_u64();
        self.spare = Some((value >> 32) as u32);
        value as u32
    }

    /// Lemire's bounded draw in [0, max], `max` below 2^32 - 1, as `Generator.integers` does it.
    pub fn bounded(&mut self, max: u32) -> u32 {
        let excluded = max + 1;
        let mut product = self.next_u32() as u64 * excluded as u64;
        let mut leftover = product as u32;
        if leftover < excluded {
            let threshold = (u32::MAX - max) % excluded;
            while leftover < threshold {
                product = self.next_u32() as u64 * excluded as u64;
                leftover = product as u32;
            }
        }
        (product >> 32) as u32
    }

    /// Masked rejection in [0, max], as `Generator.permutation` draws its swaps.
    pub fn interval(&mut self, max: u32) -> u32 {
        let mask = u32::MAX >> max.leading_zeros();
        loop {
            let value = self.next_u32() & mask;
            if value <= max {
                return value;
            }
        }
    }
}
