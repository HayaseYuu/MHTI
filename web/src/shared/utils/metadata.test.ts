import { test } from 'node:test'
import { strict as assert } from 'node:assert'
import { getMetadataId, getMetadataSource, getMetadataImageUrl, getMetadataSourceLabel } from './metadata.js'

test('旧 TMDB 结果默认显示 TMDB 来源与原始 ID', () => {
  assert.equal(getMetadataSource({ id: 123 }), 'tmdb')
  assert.equal(getMetadataId({ id: 123 }), 123)
})

test('AniList 内部负 ID 展示为正 ID', () => {
  assert.equal(getMetadataSource({ id: -456 }), 'anilist')
  assert.equal(getMetadataId({ id: -456 }), 456)
})

test('显式 AniList 身份优先使用原始 anilist_id', () => {
  assert.equal(getMetadataId({ id: -456, metadata_source: 'anilist', anilist_id: 789 }), 789)
})

test('绝对 HTTPS 海报不会被错误拼接 TMDB 地址', () => {
  const image = 'https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/456.jpg'
  assert.equal(getMetadataImageUrl(image, 'w300'), image)
})

test('TMDB 相对图片路径使用指定尺寸', () => {
  assert.equal(getMetadataImageUrl('/poster.jpg', 'w92'), 'https://image.tmdb.org/t/p/w92/poster.jpg')
})

test('无图片数据不生成 URL', () => {
  assert.equal(getMetadataImageUrl(null), null)
  assert.equal(getMetadataImageUrl(''), null)
})

for (const invalid of [
  'https://image.tmdb.org.attacker.test/poster.jpg',
  'https://attacker.test/poster.jpg',
  'http://image.tmdb.org/poster.jpg',
  'javascript:alert(1)',
  'https://user:secret@s4.anilist.co/poster.jpg',
  'https://s4.anilist.co:8443/poster.jpg',
  '//attacker.test/poster.jpg',
  'poster.jpg',
  '/../../poster.jpg',
  '/\\attacker.test/poster.jpg',
  '/poster image.jpg',
]) {
  test(`拒绝不可信或非法图片地址：${invalid}`, () => {
    assert.equal(getMetadataImageUrl(invalid), null)
  })
}

test('可信 TMDB HTTPS 绝对地址保持不变', () => {
  const image = 'https://image.tmdb.org/t/p/original/poster.jpg'
  assert.equal(getMetadataImageUrl(image), image)
})

test('拒绝非法 TMDB 尺寸参数', () => {
  assert.equal(getMetadataImageUrl('/poster.jpg', '../outside'), null)
})


test('TMDB 身份关联 AniList ID 时显示双源补全', () => {
  assert.equal(getMetadataSourceLabel({ id: 123, anilist_id: 456 }), 'TMDB + AniList')
  assert.equal(getMetadataId({ id: 123, anilist_id: 456 }), 123)
  assert.equal(getMetadataSourceLabel({ id: -456, anilist_id: 456 }), 'AniList')
})
